import os
import uuid
import shutil
import logging
import tempfile
import threading
import requests
import re
import difflib
import json
import hashlib
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Header, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Módulos do pipeline local
from audio_processor import extract_audio, separate_vocals
from transcriber import transcribe_vocals
from karaoke_generator import generate_ass_karaoke
from video_renderer import render_karaoke_video

# Configurar logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("karaoke")

app = FastAPI(title="Karaoke Maker", description="Pipeline local para geração de vídeos de karaoke")

# Diretório para templates
templates = Jinja2Templates(directory="templates")

# Locks para controle thread-safe e prevenção de processamentos concorrentes
state_lock = threading.Lock()
processing_lock = threading.Lock()

# Estado global da aplicação e persistência em disco
STATE_FILE = "/data/output/state.json"
state = {
    "status": "idle",          # idle, processing, done, error
    "step": "",                # Uploading, Extracting audio, Separating vocals, etc.
    "progress": 0,             # 0 a 100
    "error_message": "",
    "result_file": None,
    "original_filename": "final"
}

# Evento global para pausar e continuar o processamento (revisão de legenda)
correction_event = threading.Event()
segments_to_edit = []

def update_segment_words(original_seg: dict, new_text: str) -> dict:
    new_text = new_text.strip()
    original_seg["text"] = new_text
    
    # Dividir o texto editado em palavras
    new_words_list = new_text.split()
    orig_words = original_seg.get("words", [])
    
    if not new_words_list:
        original_seg["words"] = []
        return original_seg
        
    # Se o número de palavras for o mesmo, apenas substitui o texto mantendo os timestamps
    if len(new_words_list) == len(orig_words):
        for idx, word_txt in enumerate(new_words_list):
            orig_word = orig_words[idx]["word"]
            # Tentar manter o mesmo espaçamento lateral (leading/trailing spaces)
            leading_spaces = len(orig_word) - len(orig_word.lstrip(' '))
            trailing_spaces = len(orig_word.lstrip(' ')) - len(orig_word.strip(' '))
            orig_words[idx]["word"] = " " * leading_spaces + word_txt + " " * trailing_spaces
    else:
        # Se o número de palavras mudou, redistribuímos a duração igualmente
        start_time = original_seg["start"]
        end_time = original_seg["end"]
        total_dur = end_time - start_time
        if total_dur <= 0:
            total_dur = 1.0
        word_dur = total_dur / len(new_words_list)
        
        new_words = []
        for idx, word_txt in enumerate(new_words_list):
            w_start = start_time + idx * word_dur
            w_end = w_start + word_dur
            word_val = word_txt + " " if idx < len(new_words_list) - 1 else word_txt
            new_words.append({
                "word": word_val,
                "start": w_start,
                "end": w_end
            })
        original_seg["words"] = new_words
        
    return original_seg

def clean_word(w: str) -> str:
    # Remove pontuações e converte para minúsculas
    return re.sub(r'[^\w]', '', w).lower()

def align_lyrics(official_lyrics_text: str, transcribed_segments: list[dict]) -> list[dict]:
    # 1. Separar a letra oficial em linhas e palavras
    raw_lines = official_lyrics_text.strip().split('\n')
    official_lines = []
    official_words_flat = [] # Lista flat para correspondência global de sequências
    
    for line_idx, line in enumerate(raw_lines):
        line = line.strip()
        if not line:
            continue
        words = line.split()
        line_data = {
            "text": line,
            "words": words,
            "word_times": [None] * len(words) # Armazenará {"start": ..., "end": ...} para cada palavra
        }
        official_lines.append(line_data)
        for word_idx, w in enumerate(words):
            official_words_flat.append({
                "text": w,
                "clean": clean_word(w),
                "line_ref": line_data,
                "word_idx": word_idx
            })
            
    if not official_lines:
        return transcribed_segments
        
    # 2. Obter palavras transcritas pelo Whisper com seus timestamps
    transcribed_words_flat = []
    for seg in transcribed_segments:
        for w_info in seg.get("words", []):
            transcribed_words_flat.append({
                "text": w_info["word"],
                "clean": clean_word(w_info["word"]),
                "start": w_info["start"],
                "end": w_info["end"]
            })
            
    if not transcribed_words_flat:
        return transcribed_segments
        
    # 3. Alinhamento de sequências global usando difflib
    off_clean_list = [w["clean"] for w in official_words_flat]
    trans_clean_list = [w["clean"] for w in transcribed_words_flat]
    
    matcher = difflib.SequenceMatcher(None, off_clean_list, trans_clean_list)
    matching_blocks = matcher.get_matching_blocks()
    
    # Preencher correspondências diretas nos objetos de tempo das palavras das linhas
    for block in matching_blocks:
        off_start = block.a
        trans_start = block.b
        size = block.size
        for i in range(size):
            off_idx = off_start + i
            trans_idx = trans_start + i
            if off_idx < len(official_words_flat) and trans_idx < len(transcribed_words_flat):
                w_flat = official_words_flat[off_idx]
                w_flat["line_ref"]["word_times"][w_flat["word_idx"]] = {
                    "start": transcribed_words_flat[trans_idx]["start"],
                    "end": transcribed_words_flat[trans_idx]["end"]
                }
                
    # 4. Ajustar tempos locais de palavras dentro de cada linha
    for line_data in official_lines:
        times = line_data["word_times"]
        n_words = len(times)
        
        known_indices = [idx for idx, t in enumerate(times) if t is not None]
        
        if not known_indices:
            continue
            
        # Interpolação de palavras intermediárias não alinhadas
        for k in range(len(known_indices) - 1):
            idx_start = known_indices[k]
            idx_end = known_indices[k + 1]
            if idx_end - idx_start > 1:
                t_start = times[idx_start]["end"]
                t_end = times[idx_end]["start"]
                gap = t_end - t_start
                num_gaps = idx_end - idx_start
                step = gap / num_gaps if gap > 0 else 0.05
                for i in range(idx_start + 1, idx_end):
                    w_start = t_start + step * (i - idx_start - 1)
                    w_end = w_start + step
                    times[i] = {"start": w_start, "end": w_end}
                    
        # Extrapolação para trás para palavras não alinhadas no início da linha
        first_known = known_indices[0]
        if first_known > 0:
            first_start = times[first_known]["start"]
            for i in range(first_known - 1, -1, -1):
                w_end = times[i + 1]["start"]
                w_start = w_end - 0.35
                times[i] = {"start": w_start, "end": w_end}
                
        # Extrapolação para frente para palavras não alinhadas no final da linha
        last_known = known_indices[-1]
        if last_known < n_words - 1:
            last_end = times[last_known]["end"]
            for i in range(last_known + 1, n_words):
                w_start = times[i - 1]["end"]
                w_end = w_start + 0.35
                times[i] = {"start": w_start, "end": w_end}
                
    # 5. Resolver linhas inteiras que não foram alinhadas de forma alguma
    for l_idx, line_data in enumerate(official_lines):
        times = line_data["word_times"]
        if any(t is not None for t in times):
            continue
            
        # Achar o tempo final da linha anterior conhecida
        prev_line_end = 0.0
        for prev_idx in range(l_idx - 1, -1, -1):
            prev_times = [t for t in official_lines[prev_idx]["word_times"] if t is not None]
            if prev_times:
                prev_line_end = prev_times[-1]["end"]
                break
                
        # Achar o tempo inicial da próxima linha conhecida
        next_line_start = None
        for next_idx in range(l_idx + 1, len(official_lines)):
            next_times = [t for t in official_lines[next_idx]["word_times"] if t is not None]
            if next_times:
                next_line_start = next_times[0]["start"]
                break
                
        n_words = len(line_data["words"])
        default_line_dur = n_words * 0.35
        
        if next_line_start is not None:
            # Posiciona 1.5s antes do início da próxima linha conhecida
            line_end = next_line_start - 1.5
            line_start = line_end - default_line_dur
            if line_start < prev_line_end + 1.0:
                line_start = prev_line_end + 1.0
                line_end = line_start + default_line_dur
        else:
            line_start = prev_line_end + 2.0
            line_end = line_start + default_line_dur
            
        step = (line_end - line_start) / n_words
        for i in range(n_words):
            w_start = line_start + i * step
            w_end = w_start + step
            times[i] = {"start": w_start, "end": w_end}

    # 6. Reconstruir a estrutura final de segmentos com segurança de tempos crescentes
    new_segments = []
    for line_data in official_lines:
        aligned_words = []
        for word_idx, word_text in enumerate(line_data["words"]):
            time_info = line_data["word_times"][word_idx]
            
            w_start = max(0.0, time_info["start"])
            w_end = max(w_start + 0.05, time_info["end"])
            
            if word_idx < len(line_data["words"]) - 1:
                word_text += " "
                
            aligned_words.append({
                "word": word_text,
                "start": w_start,
                "end": w_end
            })
            
        if aligned_words:
            new_segments.append({
                "start": aligned_words[0]["start"],
                "end": aligned_words[-1]["end"],
                "text": line_data["text"],
                "words": aligned_words
            })
            
    return new_segments

def update_state(status: str, step: str, progress: int, error_message: str = "", result_file: str = None, original_filename: str = None):
    """Atualiza o estado global da aplicação de forma thread-safe e persiste no disco."""
    with state_lock:
        state["status"] = status
        state["step"] = step
        state["progress"] = progress
        state["error_message"] = error_message
        state["result_file"] = result_file
        if original_filename is not None:
            state["original_filename"] = original_filename
            
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                import json
                json.dump(state, f, indent=4)
        except Exception as e:
            logger.error(f"Erro ao salvar estado no disco: {e}")

@app.on_event("startup")
def startup_event():
    global state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                import json
                saved_state = json.load(f)
                
                # Se o estado salvo era "processing", significa que o container foi finalizado abruptamente (por exemplo, por falta de RAM)
                if saved_state.get("status") == "processing":
                    orig_name = saved_state.get("original_filename", "vídeo")
                    logger.warning("Detecção de reinicialização abrupta (possível OOM ou queda)!")
                    
                    state["status"] = "error"
                    state["step"] = "Interrupted"
                    state["progress"] = 0
                    state["error_message"] = "O servidor foi interrompido inesperadamente (possivelmente ficou sem memória RAM ou o container reiniciou)."
                    
                    # Salvar o estado de erro persistente
                    with open(STATE_FILE, "w", encoding="utf-8") as sf:
                        json.dump(state, sf, indent=4)
                    
                    # Notificar o erro no Telegram
                    tel_config = load_telegram_config()
                    token = tel_config.get("telegram_token")
                    chat_id = tel_config.get("telegram_chat_id")
                    if token and chat_id:
                        send_telegram_notification(
                            token,
                            chat_id,
                            f"⚠️ <b>Sal0 karaoke</b>: O servidor foi reiniciado inesperadamente ou ficou sem memória RAM (OOM) enquanto processava <b>{orig_name}</b>!"
                        )
                else:
                    state.update(saved_state)
        except Exception as e:
            logger.error(f"Erro ao carregar estado inicial no startup: {e}")

def send_telegram_notification(token: str, chat_id: str, message: str):
    """Envia uma mensagem de notificação para um chat específico via Bot do Telegram."""
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        # Timeout curto para evitar gargalos na thread
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        logger.error(f"Erro ao enviar notificação para o Telegram: {e}")

def send_telegram_video(token: str, chat_id: str, video_path: str, caption: str = ""):
    """Envia o vídeo final gerado diretamente para o chat do Telegram."""
    if not token or not chat_id or not os.path.exists(video_path):
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendVideo"
        with open(video_path, "rb") as video_file:
            files = {"video": video_file}
            data = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML"
            }
            # Timeout longo para upload (90 segundos)
            response = requests.post(url, data=data, files=files, timeout=90)
            if response.status_code == 200:
                logger.info("Vídeo de karaoke enviado com sucesso para o Telegram.")
            else:
                logger.error(f"Erro do Telegram ao enviar vídeo: {response.text}")
    except Exception as e:
        logger.error(f"Falha ao enviar vídeo de karaoke para o Telegram: {e}")

# Gerenciamento de Configurações Globais do Telegram
TELEGRAM_FILE = "/data/output/telegram.json"

class TelegramModel(BaseModel):
    telegram_token: str
    telegram_chat_id: str

def load_telegram_config() -> dict:
    """Carrega as credenciais globais do Telegram do disco."""
    if not os.path.exists(TELEGRAM_FILE):
        return {"telegram_token": "", "telegram_chat_id": ""}
    try:
        with open(TELEGRAM_FILE, "r", encoding="utf-8") as f:
            import json
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar configurações do Telegram: {e}")
        return {"telegram_token": "", "telegram_chat_id": ""}

@app.get("/api/telegram")
def get_telegram_config():
    """Endpoint para ler a credencial global do Telegram."""
    return load_telegram_config()

@app.post("/api/telegram")
def save_telegram_config(config: TelegramModel):
    """Endpoint para salvar a credencial global do Telegram."""
    try:
        os.makedirs(os.path.dirname(TELEGRAM_FILE), exist_ok=True)
        with open(TELEGRAM_FILE, "w", encoding="utf-8") as f:
            import json
            json.dump({
                "telegram_token": config.telegram_token.strip(),
                "telegram_chat_id": config.telegram_chat_id.strip()
            }, f, indent=4)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar configurações do Telegram: {e}")

# Gerenciamento de Downloads de Modelos Whisper em Background
class ModelDownloadRequest(BaseModel):
    model_size: str

model_download_status = {
    "base": {"status": "idle", "progress": 0, "error": None},
    "small": {"status": "idle", "progress": 0, "error": None},
    "medium": {"status": "idle", "progress": 0, "error": None},
    "large-v2": {"status": "idle", "progress": 0, "error": None},
    "large-v3": {"status": "idle", "progress": 0, "error": None}
}

def is_model_downloaded(model_size: str) -> bool:
    """Verifica de forma ultra leve (no disco) se o modelo Whisper já está baixado no servidor."""
    repo_id = f"Systran/faster-whisper-{model_size}"
    folder_name = f"models--{repo_id.replace('/', '--')}"
    model_dir = os.path.join("/data/output/models/whisper", folder_name)
    
    # Se a pasta principal do cache do HuggingFace não existe, não está baixado
    if not os.path.isdir(model_dir):
        return False
        
    # Verifica se há alguma pasta snapshots não vazia contendo o modelo
    snapshots_dir = os.path.join(model_dir, "snapshots")
    if os.path.isdir(snapshots_dir):
        try:
            subdirs = [os.path.join(snapshots_dir, d) for d in os.listdir(snapshots_dir) if os.path.isdir(os.path.join(snapshots_dir, d))]
            for s_dir in subdirs:
                # O model.bin é o arquivo binário essencial do ctranslate2/faster-whisper
                if os.path.exists(os.path.join(s_dir, "model.bin")):
                    return True
        except Exception:
            return False
            
    return False

def download_model_worker(model_size: str):
    """Worker em background para baixar o modelo Whisper e liberar a RAM logo em seguida."""
    try:
        from faster_whisper import WhisperModel
        import gc
        logger.info(f"Iniciando download do modelo Whisper {model_size}...")
        model_download_status[model_size]["status"] = "downloading"
        model_download_status[model_size]["progress"] = 30
        
        # Faz o download oficial
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root="/data/output/models/whisper",
            local_files_only=False
        )
        
        # Desaloca imediatamente para liberar os GBs de RAM que foram baixados
        del model
        gc.collect()
        
        model_download_status[model_size]["status"] = "done"
        model_download_status[model_size]["progress"] = 100
        logger.info(f"Download do modelo Whisper {model_size} concluído com sucesso e RAM liberada!")
    except Exception as ex:
        logger.error(f"Erro ao baixar modelo {model_size}: {ex}")
        model_download_status[model_size]["status"] = "error"
        model_download_status[model_size]["error"] = str(ex)
        model_download_status[model_size]["progress"] = 0

@app.get("/api/models")
def get_models_status(current_user: dict = Depends(get_current_user)):
    """Retorna o status de download de todos os modelos de IA."""
    result = {}
    for size in model_download_status.keys():
        downloaded = is_model_downloaded(size)
        if downloaded:
            model_download_status[size]["status"] = "done"
            model_download_status[size]["progress"] = 100
        elif model_download_status[size]["status"] == "done":
            model_download_status[size]["status"] = "idle"
            model_download_status[size]["progress"] = 0
        result[size] = model_download_status[size]
    return result

@app.post("/api/models/download")
def start_model_download(req: ModelDownloadRequest, current_user: dict = Depends(get_current_user)):
    """Dispara o download do modelo Whisper selecionado em background."""
    model_size = req.model_size
    if model_size not in model_download_status:
        raise HTTPException(status_code=400, detail="Modelo inválido.")
        
    if model_download_status[model_size]["status"] == "downloading":
        return {"message": "Download já em andamento."}
        
    model_download_status[model_size]["status"] = "downloading"
    model_download_status[model_size]["progress"] = 10
    model_download_status[model_size]["error"] = None
    
    threading.Thread(
        target=download_model_worker,
        args=(model_size,),
        daemon=True
    ).start()
    
    return {"message": f"Download do modelo {model_size} iniciado."}

# Gerenciamento de Perfis de Uso Persistentes em JSON
PROFILES_FILE = "/data/output/profiles.json"

class ProfileModel(BaseModel):
    name: str
    whisper_model: str
    font_size: int
    text_color: str
    text_position: str
    telegram_token: str = ""
    telegram_chat_id: str = ""
    subtitle_mode: str = "syllable"
    words_per_line: int = 0
    max_chars_line: int = 40
    break_on_punctuation: bool = True
    background_mode: str = "image"
    show_instrumental: bool = True
    transcribe_source: str = "vocals"
    show_next_line_preview: bool = False
    keep_first_line_visible: bool = False

def load_profiles() -> dict:
    """Carrega os perfis do arquivo JSON ou inicializa com valores padrão se não existir."""
    default_profiles = {
        "Padrão": {
            "whisper_model": "medium",
            "font_size": 32,
            "text_color": "#00FFFF",
            "text_position": "bottom",
            "telegram_token": "",
            "telegram_chat_id": "",
            "subtitle_mode": "syllable",
            "words_per_line": 0,
            "max_chars_line": 40,
            "break_on_punctuation": True,
            "background_mode": "image",
            "show_instrumental": True,
            "transcribe_source": "vocals",
            "show_next_line_preview": False,
            "keep_first_line_visible": False
        }
    }
    
    if not os.path.exists(PROFILES_FILE):
        try:
            os.makedirs(os.path.dirname(PROFILES_FILE), exist_ok=True)
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                import json
                json.dump(default_profiles, f, indent=4, ensure_ascii=False)
            return default_profiles
        except Exception as e:
            logger.error(f"Erro ao criar arquivo de perfis padrão: {e}")
            return default_profiles
            
    try:
        with open(PROFILES_FILE, "r", encoding="utf-8") as f:
            import json
            profiles = json.load(f)
            # Garantir retrocompatibilidade preenchendo campos ausentes
            for p_name, p_data in profiles.items():
                if "subtitle_mode" not in p_data:
                    p_data["subtitle_mode"] = "syllable"
                if "words_per_line" not in p_data:
                    p_data["words_per_line"] = 0
                if "max_chars_line" not in p_data:
                    p_data["max_chars_line"] = 40
                if "break_on_punctuation" not in p_data:
                    p_data["break_on_punctuation"] = True
                if "background_mode" not in p_data:
                    p_data["background_mode"] = "image"
                if "show_instrumental" not in p_data:
                    p_data["show_instrumental"] = True
                if "transcribe_source" not in p_data:
                    p_data["transcribe_source"] = "vocals"
                if "show_next_line_preview" not in p_data:
                    p_data["show_next_line_preview"] = False
                if "keep_first_line_visible" not in p_data:
                    p_data["keep_first_line_visible"] = False
            return profiles
    except Exception as e:
        logger.error(f"Erro ao carregar arquivo de perfis: {e}")
        return default_profiles

@app.get("/api/profiles")
def get_profiles(current_user: dict = Depends(get_current_user)):
    """Retorna todos os perfis salvos."""
    return load_profiles()

@app.post("/api/profiles")
def save_profile(profile: ProfileModel, current_user: dict = Depends(get_current_user)):
    """Salva ou atualiza um perfil de uso."""
    profiles = load_profiles()
    profiles[profile.name] = {
        "whisper_model": profile.whisper_model,
        "font_size": profile.font_size,
        "text_color": profile.text_color,
        "text_position": profile.text_position,
        "telegram_token": profile.telegram_token,
        "telegram_chat_id": profile.telegram_chat_id,
        "subtitle_mode": profile.subtitle_mode,
        "words_per_line": profile.words_per_line,
        "max_chars_line": profile.max_chars_line,
        "break_on_punctuation": profile.break_on_punctuation,
        "background_mode": profile.background_mode,
        "show_instrumental": profile.show_instrumental,
        "transcribe_source": profile.transcribe_source,
        "show_next_line_preview": profile.show_next_line_preview,
        "keep_first_line_visible": profile.keep_first_line_visible
    }
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            import json
            json.dump(profiles, f, indent=4, ensure_ascii=False)
        return {"status": "success", "profiles": profiles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar perfil em disco: {e}")

@app.delete("/api/profiles/{name}")
def delete_profile(name: str, current_user: dict = Depends(get_current_user)):
    """Remove um perfil de uso."""
    if name == "Padrão":
        raise HTTPException(status_code=400, detail="O perfil 'Padrão' não pode ser excluído.")
    profiles = load_profiles()
    if name in profiles:
        del profiles[name]
        try:
            with open(PROFILES_FILE, "w", encoding="utf-8") as f:
                import json
                json.dump(profiles, f, indent=4, ensure_ascii=False)
            return {"status": "success", "profiles": profiles}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao salvar arquivo após exclusão: {e}")
    raise HTTPException(status_code=404, detail="Perfil de uso não encontrado.")

LAST_PROFILE_FILE = "/data/output/last_profile.json"

@app.get("/api/last_profile")
def get_last_profile(current_user: dict = Depends(get_current_user)):
    """Retorna o nome do último perfil utilizado."""
    if os.path.exists(LAST_PROFILE_FILE):
        try:
            with open(LAST_PROFILE_FILE, "r", encoding="utf-8") as f:
                import json
                return json.load(f)
        except Exception:
            pass
    return {"last_profile": "Padrão"}

@app.post("/api/last_profile")
def save_last_profile(data: dict):
    """Salva o nome do último perfil utilizado."""
    try:
        os.makedirs(os.path.dirname(LAST_PROFILE_FILE), exist_ok=True)
        with open(LAST_PROFILE_FILE, "w", encoding="utf-8") as f:
            import json
            json.dump(data, f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar último perfil: {e}")

# --- SISTEMA DE AUTENTICAÇÃO LOCAL ---
USERS_FILE = "/data/users.json"
SESSIONS_FILE = "/data/sessions.json"

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_users(users):
    try:
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users, f, indent=4)
    except Exception as e:
        logger.error(f"Erro ao salvar usuários: {e}")

def load_sessions():
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_sessions(sessions):
    try:
        os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(sessions, f, indent=4)
    except Exception as e:
        logger.error(f"Erro ao salvar sessões: {e}")

def get_current_user(x_session_token: str = Header(None)):
    users = load_users()
    if not users:
        # Modo Setup: Sem usuários criados ainda
        return {"username": "setup_mode", "role": "setup"}
    
    if not x_session_token:
        raise HTTPException(status_code=401, detail="Sessão não fornecida.")
        
    sessions = load_sessions()
    session = sessions.get(x_session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
        
    return session

@app.get("/favicon.png")
def get_favicon():
    fav_path = "/app/templates/favicon.png"
    if os.path.exists(fav_path):
        return FileResponse(fav_path)
    return HTMLResponse(status_code=404)

@app.get("/api/auth_status")
def auth_status(x_session_token: str = Header(None)):
    users = load_users()
    if not users:
        return {"status": "setup"}
    if not x_session_token:
        return {"status": "login"}
    sessions = load_sessions()
    session = sessions.get(x_session_token)
    if not session:
        return {"status": "login"}
    return {
        "status": "authenticated",
        "username": session.get("username"),
        "role": session.get("role")
    }

@app.post("/api/setup_admin")
def setup_admin(data: dict):
    users = load_users()
    if users:
        raise HTTPException(status_code=400, detail="O administrador já foi configurado.")
        
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Usuário e senha são obrigatórios.")
        
    pw_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    users[username] = {
        "password_hash": pw_hash,
        "role": "admin"
    }
    save_users(users)
    
    token = str(uuid.uuid4())
    sessions = load_sessions()
    sessions[token] = {
        "username": username,
        "role": "admin"
    }
    save_sessions(sessions)
    
    return {"status": "success", "token": token, "username": username, "role": "admin"}

@app.post("/api/login")
def login(data: dict):
    users = load_users()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Usuário e senha são obrigatórios.")
        
    user = users.get(username)
    if not user:
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
        
    pw_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    if user.get("password_hash") != pw_hash:
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
        
    token = str(uuid.uuid4())
    sessions = load_sessions()
    sessions[token] = {
        "username": username,
        "role": user.get("role", "user")
    }
    save_sessions(sessions)
    
    return {"status": "success", "token": token, "username": username, "role": user.get("role", "user")}

@app.post("/api/logout")
def logout(x_session_token: str = Header(None)):
    if x_session_token:
        sessions = load_sessions()
        if x_session_token in sessions:
            del sessions[x_session_token]
            save_sessions(sessions)
    return {"status": "success"}

@app.get("/api/users")
def get_users(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem gerenciar usuários.")
    users = load_users()
    return [{"username": u, "role": info.get("role")} for u, info in users.items()]

@app.post("/api/create_user")
def create_user(data: dict, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem criar usuários.")
        
    username = data.get("username", "").strip()
    password = data.get("password", "")
    role = data.get("role", "user")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Usuário e senha são obrigatórios.")
        
    users = load_users()
    if username in users:
        raise HTTPException(status_code=400, detail="Este usuário já existe.")
        
    pw_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
    users[username] = {
        "password_hash": pw_hash,
        "role": role
    }
    save_users(users)
    return {"status": "success"}

@app.delete("/api/users/{username}")
def delete_user(username: str, current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem gerenciar usuários.")
    if username == current_user.get("username"):
        raise HTTPException(status_code=400, detail="Você não pode excluir a si mesmo.")
    users = load_users()
    if username in users:
        del users[username]
        save_users(users)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Usuário não encontrado.")

class EditWordModel(BaseModel):
    word: str
    start: float
    end: float

class EditSegmentModel(BaseModel):
    start: float
    end: float
    text: str
    words: list[EditWordModel] = None

class ContinueProcessModel(BaseModel):
    segments: list[EditSegmentModel]

@app.get("/api/cache_info")
def get_cache_info(current_user: dict = Depends(get_current_user)):
    cache_dir = "/data/cache"
    cache_meta_file = os.path.join(cache_dir, "cache_meta.json")
    if os.path.exists(cache_meta_file):
        try:
            with open(cache_meta_file, "r", encoding="utf-8") as f:
                import json
                meta = json.load(f)
            input_ext = meta.get("input_ext", "")
            has_audio = os.path.exists(os.path.join(cache_dir, f"original_input{input_ext}"))
            
            bg_filename = None
            if meta.get("has_bg"):
                bg_ext = meta.get("bg_ext", "")
                if os.path.exists(os.path.join(cache_dir, f"original_bg{bg_ext}")):
                    bg_filename = meta.get("bg_filename")
            
            return {
                "has_cache": has_audio,
                "audio_filename": meta.get("audio_filename", "Áudio Atual"),
                "bg_filename": bg_filename
            }
        except Exception:
            pass
    return {"has_cache": False, "audio_filename": None, "bg_filename": None}

@app.get("/api/segments_to_edit")
def get_segments_to_edit(current_user: dict = Depends(get_current_user)):
    global segments_to_edit
    return segments_to_edit

@app.post("/api/continue_process")
def continue_process(data: ContinueProcessModel, current_user: dict = Depends(get_current_user)):
    global segments_to_edit, correction_event
    if not segments_to_edit:
        raise HTTPException(status_code=400, detail="Nenhum processamento aguardando correção.")
        
    updated_segments = []
    for s in data.segments:
        seg_text = s.text.strip()
        words_list = seg_text.split()
        
        orig_words = []
        if s.words:
            orig_words = [{"word": w.word, "start": w.start, "end": w.end} for w in s.words]
            
        if len(orig_words) == len(words_list):
            orig_dur = s.words[-1].end - s.words[0].start if len(s.words) > 0 else 0
            new_dur = s.end - s.start
            if orig_dur > 0 and new_dur > 0:
                scale = new_dur / orig_dur
                t0 = s.words[0].start
                for w in orig_words:
                    w["start"] = s.start + (w["start"] - t0) * scale
                    w["end"] = s.start + (w["end"] - t0) * scale
            for idx, word_txt in enumerate(words_list):
                orig_w = orig_words[idx]["word"]
                leading_spaces = len(orig_w) - len(orig_w.lstrip(' '))
                trailing_spaces = len(orig_w.lstrip(' ')) - len(orig_w.strip(' '))
                orig_words[idx]["word"] = " " * leading_spaces + word_txt + " " * trailing_spaces
            words = orig_words
        else:
            total_dur = s.end - s.start
            if total_dur <= 0:
                total_dur = 1.0
            word_dur = total_dur / len(words_list)
            words = []
            for idx, word_txt in enumerate(words_list):
                w_start = s.start + idx * word_dur
                w_end = w_start + word_dur
                word_val = word_txt + " " if idx < len(words_list) - 1 else word_txt
                words.append({
                    "word": word_val,
                    "start": w_start,
                    "end": w_end
                })
                
        updated_segments.append({
            "start": s.start,
            "end": s.end,
            "text": seg_text,
            "words": words
        })
        
    segments_to_edit = updated_segments
    correction_event.set()
    return {"status": "success"}

@app.post("/api/cancel")
def cancel_process(current_user: dict = Depends(get_current_user)):
    import process_manager as pm
    logger.info("Solicitação de cancelamento de tarefa recebida do usuário.")
    
    # 1. Definir o flag de cancelamento
    pm.cancel_event.set()
    
    # 2. Matar o subprocesso ativo (FFmpeg ou Demucs) se existir
    with pm.process_kill_lock:
        if pm.active_process:
            try:
                logger.info(f"Finalizando subprocesso ativo (PID {pm.active_process.pid})...")
                pm.active_process.terminate()
                pm.active_process.wait(timeout=2.0)
            except Exception as e:
                logger.warning(f"Erro ao encerrar subprocesso de forma limpa: {e}. Forçando encerramento...")
                try:
                    pm.active_process.kill()
                except Exception:
                    pass
            pm.active_process = None
            
    # 3. Forçar a liberação do evento de correção para desbloquear a thread se estiver pausada
    global correction_event
    correction_event.set()
    
    # 4. Atualizar o estado do servidor para idle
    update_state("idle", "Idle", 0, error_message="Cancelado pelo usuário.")
    
    # 5. Liberar o lock de processamento
    if processing_lock.locked():
        try:
            processing_lock.release()
        except Exception:
            pass
            
    return {"status": "success", "message": "Processamento cancelado com sucesso."}

@app.get("/", response_class=HTMLResponse)
def read_index():
    """Serve a interface gráfica web da aplicação."""
    # Retorna o arquivo de template HTML compilado com Jinja2
    # Como não temos variáveis dinâmicas de renderização inicial, passamos apenas o contexto vazio
    return templates.TemplateResponse("index.html", {"request": {}})

@app.get("/api/status")
def get_status(current_user: dict = Depends(get_current_user)):
    """Retorna o progresso atual do pipeline para pooling da interface web."""
    with state_lock:
        return state

@app.post("/api/process")
def process_karaoke(
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
    audio_file: UploadFile = File(None),
    bg_file: UploadFile = File(None),
    whisper_model: str = Form("medium"),
    font_size: int = Form(32),
    text_color: str = Form("#00FFFF"),
    text_position: str = Form("bottom"),
    subtitle_mode: str = Form("syllable"),
    words_per_line: int = Form(0),
    max_chars_line: int = Form(40),
    break_on_punctuation: bool = Form(True),
    background_mode: str = Form("image"),
    show_instrumental: bool = Form(True),
    transcribe_source: str = Form("vocals"),
    show_next_line_preview: bool = Form(False),
    lyrics_text: str = Form(None),
    enable_correction: bool = Form(True),
    keep_first_line_visible: bool = Form(False)
):
    """
    Recebe os arquivos enviados, valida a concorrência e inicia o pipeline em segundo plano.
    """
    # 1. Verificar se o servidor já está processando alguma música
    if processing_lock.locked():
        raise HTTPException(
            status_code=429, 
            detail="O servidor está ocupado processando outro vídeo. Por favor, aguarde alguns minutos."
        )

    cache_dir = "/data/cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_meta_file = os.path.join(cache_dir, "cache_meta.json")

    # 2. Determinar se usaremos arquivos enviados ou o cache
    if not audio_file:
        cached_meta = {}
        if os.path.exists(cache_meta_file):
            try:
                with open(cache_meta_file, "r", encoding="utf-8") as f:
                    import json
                    cached_meta = json.load(f)
            except Exception:
                pass
        
        orig_name = cached_meta.get("original_filename")
        input_ext = cached_meta.get("input_ext")
        
        if not orig_name or not input_ext:
            raise HTTPException(
                status_code=400,
                detail="Nenhum arquivo enviado e nenhum cache disponível no servidor. Por favor, envie uma música."
            )
            
        input_audio_path = os.path.join(cache_dir, f"original_input{input_ext}")
        if not os.path.exists(input_audio_path):
            raise HTTPException(
                status_code=400,
                detail="Os arquivos de cache correspondentes não foram encontrados no servidor. Por favor, faça o upload da música."
            )
            
        if bg_file and bg_file.filename:
            # Remover background antigo
            if cached_meta.get("has_bg"):
                old_ext = cached_meta.get("bg_ext", "")
                old_bg_path = os.path.join(cache_dir, f"original_bg{old_ext}")
                if os.path.exists(old_bg_path):
                    try:
                        os.remove(old_bg_path)
                    except Exception:
                        pass
            
            bg_ext = os.path.splitext(bg_file.filename)[1]
            input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
            logger.info(f"Salvando nova imagem de fundo para o cache existente em: {input_bg_path}")
            with open(input_bg_path, "wb") as f:
                shutil.copyfileobj(bg_file.file, f)
            
            cached_meta["has_bg"] = True
            cached_meta["bg_ext"] = bg_ext
            cached_meta["bg_filename"] = bg_file.filename
            with open(cache_meta_file, "w", encoding="utf-8") as f:
                import json
                json.dump(cached_meta, f, indent=4)
        else:
            input_bg_path = None
            if cached_meta.get("has_bg"):
                bg_ext = cached_meta.get("bg_ext")
                input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
                if not os.path.exists(input_bg_path):
                    input_bg_path = None
    else:
        orig_name = os.path.splitext(audio_file.filename)[0]
        audio_ext = os.path.splitext(audio_file.filename)[1]
        
        logger.info("Novo upload recebido. Limpando cache anterior...")
        for f_name in os.listdir(cache_dir):
            f_path = os.path.join(cache_dir, f_name)
            try:
                if os.path.isfile(f_path):
                    os.remove(f_path)
                elif os.path.isdir(f_path):
                    shutil.rmtree(f_path)
            except Exception as e:
                logger.error(f"Erro ao limpar arquivo do cache {f_name}: {e}")

        input_audio_path = os.path.join(cache_dir, f"original_input{audio_ext}")
        logger.info(f"Salvando novo arquivo de áudio carregado em: {input_audio_path}")
        with open(input_audio_path, "wb") as f:
            shutil.copyfileobj(audio_file.file, f)
            
        input_bg_path = None
        has_bg = False
        bg_ext = None
        bg_filename = None
        
        if bg_file and bg_file.filename:
            bg_ext = os.path.splitext(bg_file.filename)[1]
            bg_filename = bg_file.filename
            input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
            logger.info(f"Salvando imagem de fundo carregada em: {input_bg_path}")
            with open(input_bg_path, "wb") as f:
                shutil.copyfileobj(bg_file.file, f)
            has_bg = True
            
        cached_meta = {
            "original_filename": orig_name,
            "audio_filename": audio_file.filename,
            "input_ext": audio_ext,
            "has_bg": has_bg,
            "bg_ext": bg_ext,
            "bg_filename": bg_filename
        }
        with open(cache_meta_file, "w", encoding="utf-8") as f:
            import json
            json.dump(cached_meta, f, indent=4)

    update_state("processing", "Uploading", 5, original_filename=orig_name)
        
    # 3. Adicionar tarefa na fila de execução de segundo plano síncrona
    background_tasks.add_task(
        run_pipeline, 
        input_audio_path, 
        input_bg_path, 
        whisper_model,
        font_size,
        text_color,
        text_position,
        subtitle_mode,
        words_per_line,
        max_chars_line,
        break_on_punctuation,
        background_mode,
        show_instrumental,
        transcribe_source,
        show_next_line_preview,
        lyrics_text,
        enable_correction,
        keep_first_line_visible
    )
    
    return {"status": "processing"}

def send_telegram_video_flow(token: str, chat_id: str, video_path: str, orig_name: str):
    """Auxiliar para envio de vídeo para o Telegram em segundo plano (thread dedicada)."""
    try:
        send_telegram_video(
            token=token,
            chat_id=chat_id,
            video_path=video_path,
            caption=f"🎥 <b>Sal0 karaoke</b>: Aqui está o seu vídeo de karaoke pronto para <b>{orig_name}</b>!"
        )
        send_telegram_notification(
            token=token, 
            chat_id=chat_id, 
            message=f"✅ <b>Sal0 karaoke</b>: Processamento de <b>{orig_name}</b> concluído!"
        )
    except Exception as e:
        logger.error(f"Erro no envio em segundo plano para o Telegram: {e}")

def run_pipeline(
    input_audio_path: str, 
    input_bg_path: str = None, 
    whisper_model: str = "medium",
    font_size: int = 32,
    text_color: str = "#00FFFF",
    text_position: str = "bottom",
    subtitle_mode: str = "syllable",
    words_per_line: int = 0,
    max_chars_line: int = 40,
    break_on_punctuation: bool = True,
    background_mode: str = "image",
    show_instrumental: bool = True,
    transcribe_source: str = "vocals",
    show_next_line_preview: bool = False,
    lyrics_text: str = None,
    enable_correction: bool = True,
    keep_first_line_visible: bool = False
):
    """Pipeline principal de processamento sequencial."""
    # Obter o lock de processamento exclusivo (segurança de job único)
    if not processing_lock.acquire(blocking=False):
        logger.warning("Bloqueio de concorrência ativado: Processamento já em andamento.")
        return
        
    # Carregar configuração global do Telegram do arquivo json
    tele_config = load_telegram_config()
    telegram_token = tele_config.get("telegram_token", "")
    telegram_chat_id = tele_config.get("telegram_chat_id", "")
    
    with state_lock:
        orig_name = state.get("original_filename", "final")
        
    try:
        import process_manager as pm
        pm.cancel_event.clear()
        pm.clear_active_process()
        
        # Notificação Telegram: Apenas início resumido
        send_telegram_notification(
            telegram_token, 
            telegram_chat_id, 
            f"🎙️ <b>Sal0 karaoke</b>: Iniciando processamento de <b>{orig_name}</b>..."
        )

        # Pasta de saída mapeada via volume docker-compose
        output_dir = "/data/output"
        os.makedirs(output_dir, exist_ok=True)
        
        final_mp4_path = os.path.join(output_dir, "final_karaoke.mp4")
        final_ass_path = os.path.join(output_dir, "karaoke.ass")
        
        # Limpar outputs anteriores se existirem
        if os.path.exists(final_mp4_path):
            os.remove(final_mp4_path)
        if os.path.exists(final_ass_path):
            os.remove(final_ass_path)

        # Configurar diretório de cache persistente
        cache_dir = "/data/cache"
        os.makedirs(cache_dir, exist_ok=True)
        cache_meta_file = os.path.join(cache_dir, "cache_meta.json")
        
        # Tentar ler metadados do cache anterior
        cached_meta = {}
        if os.path.exists(cache_meta_file):
            try:
                with open(cache_meta_file, "r", encoding="utf-8") as f:
                    import json
                    cached_meta = json.load(f)
            except Exception:
                pass
                
        # Verificar se a música sendo processada agora é DIFERENTE da do cache
        # Se for diferente, apagamos todo o conteúdo do cache para começar do zero!
        if cached_meta.get("original_filename") != orig_name:
            logger.info("Nova música detectada. Limpando o cache de processamento anterior...")
            for f_name in os.listdir(cache_dir):
                f_path = os.path.join(cache_dir, f_name)
                try:
                    if os.path.isfile(f_path):
                        os.remove(f_path)
                    elif os.path.isdir(f_path):
                        shutil.rmtree(f_path)
                except Exception as e:
                    logger.error(f"Erro ao limpar cache para arquivo {f_name}: {e}")
            cached_meta = {"original_filename": orig_name}
            with open(cache_meta_file, "w", encoding="utf-8") as f:
                import json
                json.dump(cached_meta, f, indent=4)

        # Criar diretório temporário para todo o processamento intermediário (Demucs, Whisper, ASS)
        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info(f"Diretório de trabalho temporário criado: {tmpdir}")
            
            # Passo 1: Extrair / Converter áudio para WAV PCM
            converted_wav = os.path.join(cache_dir, "original_converted.wav")
            if os.path.exists(converted_wav):
                logger.info("Aproveitando áudio extraído do cache.")
                update_state("processing", "Extracting audio (cached)", 15)
            else:
                pm.check_cancelled()
                update_state("processing", "Extracting audio", 15)
                send_telegram_notification(telegram_token, telegram_chat_id, "🎵 <b>Sal0 karaoke</b>: Extraindo áudio (15%)")
                extract_audio(input_audio_path, converted_wav)
            
            pm.check_cancelled()
            
            # Passo 2: Separar vocais e instrumental via Demucs
            vocals_wav = os.path.join(cache_dir, "vocals.wav")
            instrumental_wav = os.path.join(cache_dir, "instrumental.wav")
            
            if os.path.exists(vocals_wav) and os.path.exists(instrumental_wav):
                logger.info("Aproveitando áudio separado pelo Demucs do cache.")
                update_state("processing", "Separating vocals (cached)", 40)
            else:
                pm.check_cancelled()
                update_state("processing", "Separating vocals", 40)
                send_telegram_notification(telegram_token, telegram_chat_id, "✂️ <b>Sal0 karaoke</b>: Separando áudio (40%)")
                with tempfile.TemporaryDirectory() as demucs_tmp:
                    v_tmp, i_tmp = separate_vocals(converted_wav, demucs_tmp)
                    shutil.move(v_tmp, vocals_wav)
                    shutil.move(i_tmp, instrumental_wav)
                    
            pm.check_cancelled()
            
            # Passo 3: Transcrever vocais com Whisper selecionado
            segments = None
            segments_cache_file = os.path.join(cache_dir, "transcribed_segments.json")
            
            if (os.path.exists(segments_cache_file) and 
                cached_meta.get("transcribe_source") == transcribe_source and 
                cached_meta.get("whisper_model") == whisper_model):
                try:
                    with open(segments_cache_file, "r", encoding="utf-8") as f:
                        import json
                        segments = json.load(f)
                    logger.info("Aproveitando transcrição do Whisper do cache.")
                    update_state("processing", "Transcribing vocals (cached)", 70)
                except Exception as e:
                    logger.error(f"Erro ao ler cache de segmentos transcritos: {e}")
                    
            if segments is None:
                pm.check_cancelled()
                update_state("processing", "Transcribing vocals", 70)
                send_telegram_notification(telegram_token, telegram_chat_id, f"✍️ <b>Sal0 karaoke</b>: Transcrevendo voz ({whisper_model}) (70%)")
                
                transcribe_audio = vocals_wav if transcribe_source == "vocals" else converted_wav
                logger.info(f"Fonte de transcrição escolhida: {transcribe_audio} (Modo: {transcribe_source})")
                segments = transcribe_vocals(transcribe_audio, model_size=whisper_model, initial_prompt=lyrics_text)
                
                if segments:
                    with open(segments_cache_file, "w", encoding="utf-8") as f:
                        import json
                        json.dump(segments, f, indent=4)
                    cached_meta["transcribe_source"] = transcribe_source
                    cached_meta["whisper_model"] = whisper_model
                    with open(cache_meta_file, "w", encoding="utf-8") as f:
                        import json
                        json.dump(cached_meta, f, indent=4)
            
            pm.check_cancelled()
            
            if not segments:
                raise ValueError("Nenhum vocal detectado ou transcrição vazia.")
                
            # Se o usuário forneceu a letra oficial, alinhar os tempos obtidos pelo Whisper com a letra oficial
            if lyrics_text and lyrics_text.strip():
                logger.info("Aplicando alinhamento forçado local com a letra oficial fornecida...")
                segments = align_lyrics(lyrics_text, segments)
                
            pm.check_cancelled()
            
            # --- NOVO: Passo de Pausa e Correção de Legendas (se ativado pelo usuário) ---
            if enable_correction:
                global segments_to_edit, correction_event
                segments_to_edit = segments
                correction_event.clear()
                
                update_state("waiting_for_user_correction", "Correction", 75)
                
                # Notificação Telegram para o usuário entrar no app e editar
                send_telegram_notification(
                    telegram_token, 
                    telegram_chat_id, 
                    f"⚠️ <b>Sal0 karaoke</b>: A transcrição de <b>{orig_name}</b> está pronta para correção! "
                    "Entre no aplicativo web para revisar/corrigir a legenda e continuar a renderização."
                )
                
                logger.info("Aguardando o usuário corrigir as legendas na interface web...")
                # Bloqueia a thread até o usuário enviar as correções pelo endpoint /api/continue_process
                while not correction_event.is_set():
                    pm.check_cancelled()
                    correction_event.wait(timeout=1.0)
                
                logger.info("Retomando o processamento com as legendas corrigidas.")
                segments = segments_to_edit
                
                # Salvar os segmentos corrigidos também no cache, para não perder o trabalho se refazer!
                with open(segments_cache_file, "w", encoding="utf-8") as f:
                    import json
                    json.dump(segments, f, indent=4)
            
            pm.check_cancelled()
            
            # Passo 4: Gerar legendas ASS com efeitos de karaoke
            update_state("processing", "Generating subtitles", 80)
            send_telegram_notification(telegram_token, telegram_chat_id, "📝 <b>Sal0 karaoke</b>: Gerando legenda (80%)")
            ass_path = os.path.join(tmpdir, "karaoke.ass")
            generate_ass_karaoke(
                segments=segments, 
                output_ass_path=ass_path,
                font_size=font_size,
                text_color_hex=text_color,
                text_position=text_position,
                subtitle_mode=subtitle_mode,
                words_per_line=words_per_line,
                max_chars_line=max_chars_line,
                break_on_punctuation=break_on_punctuation,
                show_instrumental=show_instrumental,
                show_next_line_preview=show_next_line_preview,
                keep_first_line_visible=keep_first_line_visible
            )
            
            pm.check_cancelled()
            
            # Passo 5: Renderizar o vídeo final
            update_state("processing", "Rendering final video", 95)
            send_telegram_notification(telegram_token, telegram_chat_id, "🎬 <b>Sal0 karaoke</b>: Renderizando vídeo (95%)")
            render_karaoke_video(
                instrumental_path=instrumental_wav,
                ass_path=ass_path,
                output_mp4_path=final_mp4_path,
                background_image_path=input_bg_path,
                original_video_path=input_audio_path,
                background_mode=background_mode
            )
            
            pm.check_cancelled()
            
            # Salvar opcionalmente a legenda ASS final gerada junto com o MP4
            shutil.copy(ass_path, final_ass_path)
            
            # Passo 6: Limpar arquivos temporários (não removemos os uploads do cache)
            update_state("processing", "Cleaning temporary files", 98)
            logger.info("Preservando arquivos de entrada no cache para futuros reprocessamentos.")

            # Processamento local CONCLUÍDO na UI!
            update_state("done", "Done", 100, result_file=final_mp4_path)
            logger.info("Pipeline de Karaoke Maker concluído com sucesso!")
            
            # Liberar o lock de processamento imediatamente para que o usuário possa usar o site
            processing_lock.release()

            # Disparar envio do vídeo ao Telegram em segundo plano (thread separada)
            if telegram_token and telegram_chat_id:
                threading.Thread(
                    target=send_telegram_video_flow,
                    args=(telegram_token, telegram_chat_id, final_mp4_path, orig_name),
                    daemon=True
                ).start()
            
    except Exception as e:
        logger.exception("Ocorreu um erro catastrófico durante o processamento do pipeline.")
        # Se foi cancelado cooperativamente, salvar estado correspondente
        if "Cancelado pelo usuário" in str(e):
            update_state("idle", "Idle", 0, error_message="Processamento cancelado pelo usuário.")
        else:
            update_state("error", "Error", 0, error_message=str(e))
            send_telegram_notification(
                telegram_token, 
                telegram_chat_id, 
                f"❌ <b>Sal0 karaoke</b>: Falha ao processar <b>{orig_name}</b>. Erro: {e}"
            )
        
        # Preservamos os arquivos de entrada no cache mesmo após erro
        logger.info("Preservando arquivos de entrada no cache após erro para permitir repetições.")
            
    finally:
        # Liberar o processador de forma segura caso ainda esteja bloqueado
        if processing_lock.locked():
            try:
                processing_lock.release()
            except RuntimeError:
                pass

@app.get("/api/download")
def download_file(current_user: dict = Depends(get_current_user)):
    """Endpoint para baixar o arquivo final de vídeo karaoke."""
    file_path = "/data/output/final_karaoke.mp4"
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404, 
            detail="Arquivo de vídeo não encontrado. Por favor, processe um áudio primeiro."
        )
    # Recuperar o nome original com sufixo _karaoke
    with state_lock:
        orig_name = state.get("original_filename", "final")
    download_name = f"{orig_name}_karaoke.mp4"
    return FileResponse(
        file_path, 
        media_type="video/mp4", 
        filename=download_name
    )
