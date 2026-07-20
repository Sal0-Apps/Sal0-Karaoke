import socket
socket.setdefaulttimeout(120)  # Timeout de 120s para impedir travamentos de socket em downloads de IA
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
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Header, Depends, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Módulos do pipeline local
from audio_processor import extract_audio, separate_vocals
from transcriber import transcribe_vocals
from karaoke_generator import generate_ass_karaoke
from video_renderer import render_karaoke_video, check_has_video

# Configurar logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("karaokê")

app = FastAPI(title="Karaokê Maker", description="Pipeline local para geração de vídeos de karaokê")

# Diretório para templates
templates = Jinja2Templates(directory="templates")

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

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        import os
        salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), 100000)
    return dk.hex(), salt

def download_youtube(url: str, cache_dir: str) -> tuple[str, str]:
    """Baixa o melhor vídeo/áudio do YouTube usando yt-dlp com expurgo prévio e 'overwrites': True."""
    import yt_dlp
    
    # Expurgo prévio obrigatorio de qualquer original_input.* no cache para impedir que o yt-dlp pule o download
    for f in os.listdir(cache_dir):
        if f.startswith("original_input."):
            try:
                os.remove(os.path.join(cache_dir, f))
            except Exception:
                pass
    
    ydl_opts_primary = {
        'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
        'outtmpl': os.path.join(cache_dir, 'original_input.%(ext)s'),
        'merge_output_format': 'mp4',
        'remux_video': 'mp4',
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
    }
    
    ydl_opts_fallback = {
        'format': 'best',
        'outtmpl': os.path.join(cache_dir, 'original_input.%(ext)s'),
        'merge_output_format': 'mp4',
        'remux_video': 'mp4',
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
    }
    
    title = "YouTube Video"
    try:
        logger.info("Tentando baixar do YouTube com formato primário (<=1080p)...")
        with yt_dlp.YoutubeDL(ydl_opts_primary) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'YouTube Video')
    except Exception as e:
        logger.warning(f"Falha ao baixar no formato primário ({e}). Tentando formato fallback 'best'...")
        with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'YouTube Video')
        
    # O arquivo final será .mp4 devido ao merge e remux
    file_path = os.path.join(cache_dir, 'original_input.mp4')
    if not os.path.exists(file_path):
        for f in os.listdir(cache_dir):
            if f.startswith("original_input."):
                file_path = os.path.join(cache_dir, f)
                break
    return file_path, title

def get_current_user(
    x_session_token: str = Header(None),
    authorization: str = Header(None),
    token: str = Query(None)
):
    users = load_users()
    if not users:
        # Modo Setup: Sem usuários criados ainda
        return {"username": "setup_mode", "role": "setup"}

    # Aceita x-session-token, Authorization: Bearer <token>, ou ?token=
    active_token = x_session_token or token
    if not active_token and authorization:
        if authorization.lower().startswith("bearer "):
            active_token = authorization[7:].strip()

    if not active_token:
        raise HTTPException(status_code=401, detail="Sessão não fornecida.")

    sessions = load_sessions()
    session = sessions.get(active_token)
    if not session:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")

    # Verificar TTL da sessão (30 dias)
    import time
    created_at = session.get("created_at", 0)
    if created_at and (time.time() - created_at) > (30 * 24 * 3600):
        # Sessão expirada - remover e rejeitar
        sessions.pop(active_token, None)
        save_sessions(sessions)
        raise HTTPException(status_code=401, detail="Sessão expirada. Faça login novamente.")

    return session

# Locks para controle thread-safe e prevenção de processamentos concorrentes
state_lock = threading.Lock()
processing_lock = threading.Lock()

# Proteção contra brute-force no login
_login_attempts: dict = {}  # {ip_or_user: {"count": int, "locked_until": float}}
_login_lock = threading.Lock()
MAX_LOGIN_ATTEMPTS = 10   # tentativas antes do bloqueio
LOCKOUT_SECONDS = 300     # 5 minutos de bloqueio

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
    # Garantir diretórios da biblioteca
    for folder in ["videos", "photos", "history"]:
        os.makedirs(f"/data/library/{folder}", exist_ok=True)
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
                            f"⚠️ <b>Sal0 Karaokê</b>: O servidor foi reiniciado inesperadamente ou ficou sem memória RAM (OOM) enquanto processava <b>{orig_name}</b>!"
                        )
                else:
                    state.update(saved_state)
        except Exception as e:
            logger.error(f"Erro ao carregar estado inicial no startup: {e}")

def _send_telegram_notification_worker(token: str, chat_id: str, message: str):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Erro ao enviar notificação para o Telegram: {e}")

def send_telegram_notification(token: str, chat_id: str, message: str):
    """Envia uma mensagem de notificação para um chat específico via Bot do Telegram sem bloquear o pipeline ( Thread Assíncrona )."""
    if not token or not chat_id:
        return
    threading.Thread(
        target=_send_telegram_notification_worker,
        args=(token, chat_id, message),
        daemon=True
    ).start()

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
                logger.info("Vídeo de karaokê enviado com sucesso para o Telegram.")
            else:
                # Log sem expor dados sensíveis da resposta do Telegram
                logger.error(f"Erro do Telegram ao enviar vídeo: HTTP {response.status_code}")
    except Exception as e:
        logger.error(f"Falha ao enviar vídeo de karaokê para o Telegram: {e}")

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
def get_telegram_config(current_user: dict = Depends(get_current_user)):
    """Endpoint para ler a credencial global do Telegram."""
    config = load_telegram_config()
    # Mascarar token parcialmente na resposta para não expor o valor completo
    token = config.get("telegram_token", "")
    if token and len(token) > 8:
        config["telegram_token"] = token[:6] + "***" + token[-4:]
    return config

@app.post("/api/telegram")
def save_telegram_config(config: TelegramModel, current_user: dict = Depends(get_current_user)):
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

# Gerenciamento de Configuração de IP/URL Externa
EXTERNAL_URL_FILE = "/data/output/external_url.json"

class ExternalUrlModel(BaseModel):
    external_url: str

def load_external_url_config() -> dict:
    """Carrega a URL/IP externo do disco."""
    if not os.path.exists(EXTERNAL_URL_FILE):
        return {"external_url": ""}
    try:
        with open(EXTERNAL_URL_FILE, "r", encoding="utf-8") as f:
            import json
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar URL externa: {e}")
        return {"external_url": ""}

@app.get("/api/external_url")
def get_external_url_config(current_user: dict = Depends(get_current_user)):
    """Endpoint para ler a URL/IP externo salvo."""
    return load_external_url_config()

@app.post("/api/external_url")
def save_external_url_config(config: ExternalUrlModel, current_user: dict = Depends(get_current_user)):
    """Endpoint para salvar a URL/IP externo."""
    try:
        os.makedirs(os.path.dirname(EXTERNAL_URL_FILE), exist_ok=True)
        with open(EXTERNAL_URL_FILE, "w", encoding="utf-8") as f:
            import json
            json.dump({
                "external_url": config.external_url.strip()
            }, f, indent=4)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar URL externa: {e}")


# Gerenciamento de Downloads de Modelos Whisper em Background
class ModelDownloadRequest(BaseModel):
    model_size: str = None
    model: str = None

class YouTubePresetModel(BaseModel):
    youtube_url: str

model_download_status = {
    "large-v3-turbo": {"status": "idle", "progress": 0, "error": None},
    "medium": {"status": "idle", "progress": 0, "error": None},
    "small": {"status": "idle", "progress": 0, "error": None},
    "tiny": {"status": "idle", "progress": 0, "error": None},
    "large-v3": {"status": "idle", "progress": 0, "error": None}
}

def resolve_whisper_repo(model_size: str) -> str:
    """Mapeia os 5 modelos suportados para seus repositórios no Hugging Face (Sal0 Karaoke v4.0.0)."""
    mapping = {
        "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo",
        "medium": "Systran/faster-whisper-medium",
        "small": "Systran/faster-whisper-small",
        "tiny": "Systran/faster-whisper-tiny",
        "large-v3": "Systran/faster-whisper-large-v3"
    }
    return mapping.get(model_size.lower().strip(), model_size)

def is_model_downloaded(model_size: str) -> bool:
    """Verifica nos diretórios locais se um dos 5 modelos Whisper v4.0.0 já foi baixado."""
    key = model_size.lower().strip()
    
    if key == "large-v3-turbo":
        match_fn = lambda name: "turbo" in name or "large-v3-turbo" in name
    elif key == "large-v3":
        match_fn = lambda name: "large-v3" in name and "turbo" not in name
    elif key == "medium":
        match_fn = lambda name: "medium" in name
    elif key == "small":
        match_fn = lambda name: "small" in name
    elif key == "tiny" or key == "base":
        match_fn = lambda name: "tiny" in name or "base" in name
    else:
        match_fn = lambda name: key in name

    search_roots = [
        "/data/output/models/whisper",
        "/root/.cache/huggingface/hub",
        "/root/.cache/whisper",
        os.path.expanduser("~/.cache/huggingface/hub"),
        os.path.expanduser("~/.cache/whisper")
    ]

    for root in search_roots:
        if not os.path.exists(root):
            continue
        try:
            for entry in os.listdir(root):
                entry_path = os.path.join(root, entry)
                if os.path.isdir(entry_path) and match_fn(entry.lower()):
                    for r, dirs, files in os.walk(entry_path):
                        if any(f in files for f in ["model.bin", "model.safetensors", "config.json", "pytorch_model.bin", "model.pt", "vocabulary.json"]):
                            return True
        except Exception as e:
            logger.warning(f"Erro ao verificar modelos em {root}: {e}")
    return False

def download_model_worker(model_size: str):
    """Worker em background para baixar o modelo Whisper e liberar a RAM."""
    try:
        from faster_whisper import WhisperModel
        import gc
        logger.info(f"Iniciando download do modelo Whisper {model_size}...")
        model_download_status[model_size]["status"] = "downloading"
        model_download_status[model_size]["progress"] = 30
        
        repo_id = resolve_whisper_repo(model_size)
        save_dir = "/data/output/models/whisper"
        os.makedirs(save_dir, exist_ok=True)
        
        try:
            logger.info(f"Baixando repositório {repo_id} em {save_dir}...")
            model = WhisperModel(
                repo_id,
                device="cpu",
                compute_type="int8",
                download_root=save_dir
            )
            del model
            gc.collect()
        except Exception as e1:
            logger.warning(f"Tentativa com {repo_id} retornou: {e1}, tentando {model_size}...")
            model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8",
                download_root=save_dir
            )
            del model
            gc.collect()
            
        model_download_status[model_size]["status"] = "done"
        model_download_status[model_size]["progress"] = 100
        logger.info(f"Download do modelo Whisper {model_size} concluído com sucesso!")
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
    model_size = req.model_size or req.model
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

def run_youtube_download_bg(url: str):
    cache_dir = "/data/cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_meta_file = os.path.join(cache_dir, "cache_meta.json")
    
    # Carregar configuração global do Telegram do arquivo json
    tele_config = load_telegram_config()
    telegram_token = tele_config.get("telegram_token", "")
    telegram_chat_id = tele_config.get("telegram_chat_id", "")
    
    try:
        update_state("processing", "Downloading YouTube", 5, original_filename="Baixando do YouTube...")
        
        send_telegram_notification(
            telegram_token,
            telegram_chat_id,
            f"🌐 <b>Sal0 Karaokê</b>: Iniciando download do YouTube de <b>{url}</b>..."
        )
        
        input_audio_path, title = download_youtube(url, cache_dir)
        ext = os.path.splitext(input_audio_path)[1]
        
        cached_meta = {
            "youtube_url": url,
            "original_filename": title,
            "audio_filename": title + ext,
            "input_ext": ext,
            "has_bg": False,
            "bg_ext": None,
            "bg_filename": None,
            "lyrics_text": ""
        }
        with open(cache_meta_file, "w", encoding="utf-8") as f:
            json.dump(cached_meta, f, indent=4)
            
        # Salvar também na biblioteca de vídeos permanentemente
        try:
            lib_video_dir = "/data/library/videos"
            os.makedirs(lib_video_dir, exist_ok=True)
            safe_title = "".join([c for c in title if c.isalnum() or c in ' ._-']).strip() or "youtube_download"
            dest_file = os.path.join(lib_video_dir, f"{safe_title}{ext}")
            shutil.copy2(input_audio_path, dest_file)
            logger.info(f"Vídeo do YouTube adicionado à biblioteca: {dest_file}")
        except Exception as copy_err:
            logger.error(f"Erro ao salvar vídeo do YouTube na biblioteca: {copy_err}")

        send_telegram_notification(
            telegram_token,
            telegram_chat_id,
            f"📥 <b>Sal0 Karaokê</b>: Download concluído e adicionado à Biblioteca! <b>{title}</b>"
        )
        
        update_state("done", "Download Concluído e Adicionado à Biblioteca!", 100, original_filename=title)
        
    except Exception as e:
        logger.error(f"Erro no download do YouTube em background: {e}")
        update_state("error", "Error", 0, error_message=f"Falha ao baixar vídeo do YouTube: {e}")
        send_telegram_notification(
            telegram_token,
            telegram_chat_id,
            f"❌ <b>Sal0 Karaokê</b>: Falha ao baixar vídeo do YouTube. Erro: {e}"
        )

def download_bg_youtube(url: str, cache_dir: str) -> tuple[str, str]:
    """Baixa apenas o fluxo de vídeo do YouTube (sem áudio) para uso como fundo com expurgo e overwrites: True."""
    import yt_dlp
    
    # Expurgo prévio obrigatorio de qualquer bg_yt_raw.* no cache
    for f in os.listdir(cache_dir):
        if f.startswith("bg_yt_raw.") or f.startswith("bg_yt_no_audio."):
            try:
                os.remove(os.path.join(cache_dir, f))
            except Exception:
                pass
    
    ydl_opts_primary = {
        'format': 'bestvideo[height<=1080]/bestvideo/best',
        'outtmpl': os.path.join(cache_dir, 'bg_yt_raw.%(ext)s'),
        'merge_output_format': 'mp4',
        'remux_video': 'mp4',
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
    }
    ydl_opts_fallback = {
        'format': 'best',
        'outtmpl': os.path.join(cache_dir, 'bg_yt_raw.%(ext)s'),
        'merge_output_format': 'mp4',
        'remux_video': 'mp4',
        'overwrites': True,
        'quiet': True,
        'no_warnings': True,
    }
    
    title = "Fundo YouTube"
    try:
        with yt_dlp.YoutubeDL(ydl_opts_primary) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Fundo YouTube')
    except Exception as e:
        logger.warning(f"Falha no formato primário do fundo YouTube ({e}). Tentando fallback...")
        try:
            with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Fundo YouTube')
        except Exception as err:
            logger.error(f"Erro fatal no download de fundo YouTube: {err}")
        
    raw_file = os.path.join(cache_dir, 'bg_yt_raw.mp4')
    if not os.path.exists(raw_file):
        for f in os.listdir(cache_dir):
            if f.startswith("bg_yt_raw."):
                raw_file = os.path.join(cache_dir, f)
                break
                
    # Remover o áudio usando ffmpeg (-an) para garantir 100% sem som
    no_audio_file = os.path.join(cache_dir, 'bg_yt_no_audio.mp4')
    try:
        cmd = ['ffmpeg', '-y', '-i', raw_file, '-c:v', 'copy', '-an', no_audio_file]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except Exception as err:
        logger.error(f"Erro ao remover áudio do fundo com ffmpeg: {err}")
        no_audio_file = raw_file
        
    return no_audio_file, title

def run_bg_youtube_download_bg(url: str):
    cache_dir = "/data/cache"
    os.makedirs(cache_dir, exist_ok=True)
    
    tele_config = load_telegram_config()
    telegram_token = tele_config.get("telegram_token", "")
    telegram_chat_id = tele_config.get("telegram_chat_id", "")
    
    try:
        update_state("processing", "Downloading YouTube Background", 5, original_filename="Baixando fundo do YouTube...")
        
        send_telegram_notification(
            telegram_token,
            telegram_chat_id,
            f"🖼️ <b>Sal0 Karaokê</b>: Iniciando download de fundo do YouTube (sem áudio) de <b>{url}</b>..."
        )
        
        no_audio_path, title = download_bg_youtube(url, cache_dir)
        ext = os.path.splitext(no_audio_path)[1]
        
        # Salvar na biblioteca de fotos/vídeos de fundo permanentemente
        try:
            lib_photos_dir = "/data/library/photos"
            os.makedirs(lib_photos_dir, exist_ok=True)
            safe_title = "".join([c for c in title if c.isalnum() or c in ' ._-']).strip() or "fundo_youtube"
            dest_filename = f"{safe_title}_sem_audio{ext}"
            dest_file = os.path.join(lib_photos_dir, dest_filename)
            shutil.copy2(no_audio_path, dest_file)
            logger.info(f"Vídeo de fundo sem áudio salvo na biblioteca: {dest_file}")
        except Exception as copy_err:
            logger.error(f"Erro ao salvar fundo do YouTube na biblioteca: {copy_err}")

        send_telegram_notification(
            telegram_token,
            telegram_chat_id,
            f"🖼️ <b>Sal0 Karaokê</b>: Fundo do YouTube baixado sem áudio e salvo na Biblioteca! <b>{title}</b>"
        )
        
        update_state("done", "Download Concluído e Adicionado à Biblioteca!", 100, original_filename=title)
        
    except Exception as e:
        logger.error(f"Erro no download de fundo do YouTube em background: {e}")
        update_state("error", "Error", 0, error_message=f"Falha ao baixar fundo do YouTube: {e}")
        send_telegram_notification(
            telegram_token,
            telegram_chat_id,
            f"❌ <b>Sal0 Karaokê</b>: Falha ao baixar fundo do YouTube. Erro: {e}"
        )


@app.post("/api/download-youtube-preset")
def download_youtube_preset(
    data: YouTubePresetModel,
    current_user: dict = Depends(get_current_user)
):
    if processing_lock.locked():
        raise HTTPException(
            status_code=429,
            detail="O servidor está ocupado processando outro vídeo. Por favor, aguarde alguns minutos."
        )
        
    url = data.youtube_url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL do YouTube vazia.")
        
    threading.Thread(target=run_youtube_download_bg, args=(url,), daemon=True).start()
    return {"status": "started"}

# Gerenciamento de Perfis de Uso Persistentes em JSON
@app.post("/api/download-bg-youtube-preset")
def download_bg_youtube_preset(
    data: YouTubePresetModel,
    current_user: dict = Depends(get_current_user)
):
    if processing_lock.locked():
        raise HTTPException(
            status_code=429,
            detail="O servidor está ocupado processando outro vídeo. Por favor, aguarde alguns minutos."
        )
        
    url = data.youtube_url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL do YouTube vazia.")
        
    threading.Thread(target=run_bg_youtube_download_bg, args=(url,), daemon=True).start()
    return {"status": "started"}


SAVED_LYRICS_FILE = "/data/output/saved_lyrics.txt"

class LyricsModel(BaseModel):
    lyrics_text: str = ""

@app.get("/api/lyrics")
def get_saved_lyrics(current_user: dict = Depends(get_current_user)):
    """Retorna a letra salva no servidor."""
    if os.path.exists(SAVED_LYRICS_FILE):
        try:
            with open(SAVED_LYRICS_FILE, "r", encoding="utf-8") as f:
                return {"lyrics_text": f.read()}
        except Exception as e:
            logger.error(f"Erro ao ler letra do servidor: {e}")
    return {"lyrics_text": ""}

@app.post("/api/lyrics")
def save_lyrics_server(data: LyricsModel, current_user: dict = Depends(get_current_user)):
    """Salva a letra da música no servidor."""
    try:
        os.makedirs(os.path.dirname(SAVED_LYRICS_FILE), exist_ok=True)
        with open(SAVED_LYRICS_FILE, "w", encoding="utf-8") as f:
            f.write(data.lyrics_text or "")
        return {"status": "saved"}
    except Exception as e:
        logger.error(f"Erro ao salvar letra no servidor: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar letra no servidor: {e}")

@app.delete("/api/lyrics")
def delete_lyrics_server(current_user: dict = Depends(get_current_user)):
    """Exclui a letra salva do servidor."""
    try:
        if os.path.exists(SAVED_LYRICS_FILE):
            os.remove(SAVED_LYRICS_FILE)
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Erro ao excluir letra do servidor: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao excluir letra do servidor: {e}")



# Sistema de Logs de Diagnóstico v4.0.0
DIAGNOSTIC_LOG_FILE = "/data/output/app_diagnostic.log"

def log_diagnostic(message: str, level: str = "INFO"):
    """Escreve mensagens detalhadas no arquivo de log de diagnóstico."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] [{level}] {message}\n"
    print(formatted_msg, end="")
    try:
        os.makedirs(os.path.dirname(DIAGNOSTIC_LOG_FILE), exist_ok=True)
        with open(DIAGNOSTIC_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted_msg)
    except Exception:
        pass

@app.get("/api/logs/download")
def download_diagnostic_logs(current_user: dict = Depends(get_current_user)):
    """Endpoint para baixar os logs detalhados de diagnóstico do servidor."""
    if os.path.exists(DIAGNOSTIC_LOG_FILE):
        return FileResponse(
            DIAGNOSTIC_LOG_FILE,
            media_type="text/plain",
            filename="sal0_karaoke_diagnostic_logs.txt"
        )
    # Se não existir ainda o arquivo de log dedicado, cria um com o estado atual
    try:
        log_diagnostic("Log de diagnóstico gerado pelo usuário.")
        return FileResponse(
            DIAGNOSTIC_LOG_FILE,
            media_type="text/plain",
            filename="sal0_karaoke_diagnostic_logs.txt"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar arquivo de logs: {e}")


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
                if "pause_for_editing" not in p_data:
                    p_data["pause_for_editing"] = False
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
def save_last_profile(data: dict, current_user: dict = Depends(get_current_user)):
    """Salva o nome do último perfil utilizado."""
    try:
        os.makedirs(os.path.dirname(LAST_PROFILE_FILE), exist_ok=True)
        with open(LAST_PROFILE_FILE, "w", encoding="utf-8") as f:
            import json
            json.dump(data, f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar último perfil: {e}")



@app.get("/favicon.png")
def get_favicon():
    fav_path = os.path.join(os.path.dirname(__file__), "templates", "favicon.png")
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
        
    pw_hash, salt = hash_password(password)
    users[username] = {
        "password_hash": pw_hash,
        "salt": salt,
        "role": "admin"
    }
    save_users(users)
    
    import time
    token = str(uuid.uuid4())
    sessions = load_sessions()
    sessions[token] = {
        "username": username,
        "role": "admin",
        "created_at": time.time()
    }
    save_sessions(sessions)

    return {"status": "success", "token": token, "username": username, "role": "admin"}

@app.post("/api/login")
def login(data: dict):
    import time
    users = load_users()
    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Usuário e senha são obrigatórios.")

    # Proteção contra brute-force por nome de usuário
    with _login_lock:
        attempt_info = _login_attempts.get(username, {"count": 0, "locked_until": 0})
        if time.time() < attempt_info.get("locked_until", 0):
            remaining = int(attempt_info["locked_until"] - time.time())
            raise HTTPException(
                status_code=429,
                detail=f"Conta temporariamente bloqueada. Tente novamente em {remaining} segundos."
            )

    user = users.get(username)
    if not user:
        # Registrar tentativa falha mesmo para usuários inexistentes (evita user enumeration timing)
        with _login_lock:
            info = _login_attempts.get(username, {"count": 0, "locked_until": 0})
            info["count"] = info.get("count", 0) + 1
            if info["count"] >= MAX_LOGIN_ATTEMPTS:
                info["locked_until"] = time.time() + LOCKOUT_SECONDS
                info["count"] = 0
            _login_attempts[username] = info
        raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
        
    # Lógica de migração automática do SHA-256 legado para PBKDF2
    salt = user.get("salt")
    if not salt:
        # Tentar validar usando o sha256 simples antigo
        legacy_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if user.get("password_hash") != legacy_hash:
            raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
        # Se validado com sucesso, migramos imediatamente!
        pw_hash, new_salt = hash_password(password)
        user["password_hash"] = pw_hash
        user["salt"] = new_salt
        users[username] = user
        save_users(users)
        logger.info(f"Usuário {username} migrado com sucesso para criptografia PBKDF2.")
    else:
        # Validar usando PBKDF2 com o salt correspondente
        check_hash, _ = hash_password(password, salt=salt)
        if user.get("password_hash") != check_hash:
            raise HTTPException(status_code=401, detail="Usuário ou senha incorretos.")
        
    # Reset contador de tentativas após login bem-sucedido
    with _login_lock:
        _login_attempts.pop(username, None)

    import time
    token = str(uuid.uuid4())
    sessions = load_sessions()
    sessions[token] = {
        "username": username,
        "role": user.get("role", "user"),
        "created_at": time.time()
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
        
    pw_hash, salt = hash_password(password)
    users[username] = {
        "password_hash": pw_hash,
        "salt": salt,
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

# --- SISTEMA DE BIBLIOTECA & HISTÓRICO ---
LIBRARY_DIR = "/data/library"

@app.get("/api/library")
def get_library_files(current_user: dict = Depends(get_current_user)):
    """Retorna as listas de arquivos disponíveis na biblioteca (videos, photos, history)."""
    result = {"videos": [], "photos": [], "history": []}
    for section in ["videos", "photos", "history"]:
        path = os.path.join(LIBRARY_DIR, section)
        if os.path.exists(path):
            try:
                files = sorted(os.listdir(path))
                result[section] = [f for f in files if os.path.isfile(os.path.join(path, f)) and not f.startswith('.') and not f.startswith('tmp') and not f.startswith('original_') and not f.startswith('cache_')]
            except Exception as e:
                logger.error(f"Erro ao listar biblioteca {section}: {e}")
    return result

@app.post("/api/library/upload")
def upload_to_library(
    section: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """Realiza o upload direto de um arquivo para uma seção específica da biblioteca."""
    if section not in ["videos", "photos"]:
        raise HTTPException(status_code=400, detail="Seção de biblioteca inválida.")
    
    target_dir = os.path.join(LIBRARY_DIR, section)
    os.makedirs(target_dir, exist_ok=True)
    
    safe_name = os.path.basename(file.filename)
    dest_path = os.path.join(target_dir, safe_name)
    
    try:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        logger.info(f"Arquivo {safe_name} adicionado à biblioteca {section}.")
        return {"status": "success", "filename": safe_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar arquivo na biblioteca: {e}")

@app.post("/api/library/save_history")
def save_to_history(data: dict, current_user: dict = Depends(get_current_user)):
    """Salva a produção final (final_karaoke.mp4) no histórico permanente com nome customizado."""
    title = data.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="O título é obrigatório.")
    
    safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
    if not safe_title.lower().endswith(".mp4"):
        safe_title += ".mp4"
        
    final_mp4 = "/data/output/final_karaoke.mp4"
    if not os.path.exists(final_mp4):
        raise HTTPException(status_code=400, detail="Nenhum vídeo finalizado encontrado para salvar no histórico.")
        
    dest_dir = os.path.join(LIBRARY_DIR, "history")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, safe_title)
    
    try:
        shutil.copy2(final_mp4, dest_path)
        logger.info(f"Vídeo de karaokê salvo no histórico: {safe_title}")
        return {"status": "success", "filename": safe_title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar vídeo no histórico: {e}")

@app.delete("/api/library/{section}/{filename}")
def delete_from_library(section: str, filename: str, current_user: dict = Depends(get_current_user)):
    """Exclui fisicamente um arquivo da biblioteca."""
    if section not in ["videos", "photos", "history"]:
        raise HTTPException(status_code=400, detail="Seção inválida.")
        
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(LIBRARY_DIR, section, safe_filename)
    
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.info(f"Arquivo {safe_filename} excluído da biblioteca {section}.")
            return {"status": "success"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao remover arquivo: {e}")
            
    raise HTTPException(status_code=404, detail="Arquivo não encontrado na biblioteca.")

@app.get("/api/library/download/{section}/{filename}")
def download_from_library(section: str, filename: str, current_user: dict = Depends(get_current_user)):
    """Faz o download de um arquivo da biblioteca."""
    if section not in ["videos", "photos", "history"]:
        raise HTTPException(status_code=400, detail="Seção inválida.")
        
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(LIBRARY_DIR, section, safe_filename)
    
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=safe_filename)
        
    raise HTTPException(status_code=404, detail="Arquivo não encontrado na biblioteca.")

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
            bg_is_video = False
            if meta.get("has_bg"):
                bg_ext = meta.get("bg_ext", "")
                if os.path.exists(os.path.join(cache_dir, f"original_bg{bg_ext}")):
                    bg_filename = meta.get("bg_filename")
                    if bg_ext.lower() in [".mp4", ".webm", ".mov", ".mkv", ".avi"]:
                        bg_is_video = True
            
            return {
                "has_cache": has_audio,
                "audio_filename": meta.get("audio_filename", "Áudio Atual"),
                "bg_filename": bg_filename,
                "lyrics_text": meta.get("lyrics_text", ""),
                "bg_is_video": bg_is_video
            }
        except Exception:
            pass
    return {"has_cache": False, "audio_filename": None, "bg_filename": None, "lyrics_text": "", "bg_is_video": False}

@app.get("/api/cache/background")
def get_cached_background(current_user: dict = Depends(get_current_user)):
    """Serve o arquivo de background em cache (imagem ou vídeo) ou uma paisagem padrão como fallback."""
    cache_dir = "/data/cache"
    cache_meta_file = os.path.join(cache_dir, "cache_meta.json")
    if os.path.exists(cache_meta_file):
        try:
            with open(cache_meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("has_bg"):
                bg_ext = meta.get("bg_ext", "")
                bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
                if os.path.exists(bg_path):
                    media_type = "image/jpeg"
                    if bg_ext.lower() in [".png"]:
                        media_type = "image/png"
                    elif bg_ext.lower() in [".gif"]:
                        media_type = "image/gif"
                    elif bg_ext.lower() in [".mp4", ".mov", ".mkv", ".webm", ".avi"]:
                        media_type = "video/mp4"
                    return FileResponse(bg_path, media_type=media_type)
        except Exception:
            pass
            
    # Fallback para paisagem aleatória
    default_bg = get_random_default_background()
    if default_bg and os.path.exists(default_bg):
        return FileResponse(default_bg, media_type="image/jpeg")
    
    raise HTTPException(status_code=404, detail="Nenhum plano de fundo disponível em cache.")


@app.post("/api/skip_edit")
def skip_edit(current_user: dict = Depends(get_current_user)):
    """Continua o processamento sem alterar as legendas."""
    global correction_event
    correction_event.set()
    return {"status": "success", "message": "Renderização retomada sem alterações."}


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

def purge_audio_cache_directory(cache_dir: str):
    """Apaga todos os arquivos e subpastas de áudio do cache, preservando apenas imagens de fundo se necessário."""
    if os.path.exists(cache_dir):
        for f_name in os.listdir(cache_dir):
            if f_name.startswith("original_bg"):
                continue
            f_path = os.path.join(cache_dir, f_name)
            try:
                if os.path.isfile(f_path):
                    os.remove(f_path)
                elif os.path.isdir(f_path):
                    shutil.rmtree(f_path)
            except Exception as e:
                logger.warning(f"Erro ao purgar {f_name} do cache: {e}")


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
    enable_correction: bool = Form(False),
    keep_first_line_visible: bool = Form(False),
    pause_for_editing: bool = Form(False),
    youtube_url: str = Form(None),
    library_audio: str = Form(None),
    library_bg: str = Form(None),
    save_to_library: bool = Form(False),
    only_remove_vocals: bool = Form(False)
):
    """
    Recebe os arquivos enviados, valida a concorrência e inicia o pipeline em segundo plano.
    """
    # 1. Verificar se o servidor já está processando alguma música
    if processing_lock.locked():
        with state_lock:
            if state.get("status") in ["idle", "error", "done"]:
                try:
                    processing_lock.release()
                    logger.info("Failsafe v4.0.0: Lock de concorrência obsoleto liberado com sucesso.")
                except Exception:
                    pass
            else:
                raise HTTPException(
                    status_code=429, 
                    detail="O servidor está ocupado processando outro vídeo. Por favor, aguarde alguns minutos."
                )

    cache_dir = "/data/cache"
    os.makedirs(cache_dir, exist_ok=True)
    cache_meta_file = os.path.join(cache_dir, "cache_meta.json")

    # Se uma música da biblioteca foi explicitamente selecionada, anular youtube_url para priorizar a biblioteca
    if library_audio and library_audio.strip():
        youtube_url = None

    # 2. Determinar se usaremos arquivos enviados, biblioteca, YouTube ou cache
    if youtube_url and youtube_url.strip():
        # Verificar se já baixamos essa exata URL no cache
        already_downloaded = False
        orig_name = "Baixando do YouTube..."
        input_audio_path = os.path.join(cache_dir, "original_input.mp4")
        if os.path.exists(cache_meta_file):
            try:
                with open(cache_meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    if meta.get("youtube_url") == youtube_url.strip():
                        ext = meta.get("input_ext", ".mp4")
                        orig_file = os.path.join(cache_dir, f"original_input{ext}")
                        if os.path.exists(orig_file):
                            already_downloaded = True
                            orig_name = meta.get("original_filename", "YouTube Video")
                            input_audio_path = orig_file
            except Exception:
                pass
                
        input_bg_path = None
        has_bg = False
        bg_ext = None
        bg_filename = None
        
        if bg_file and bg_file.filename:
            bg_ext = os.path.splitext(bg_file.filename)[1]
            bg_filename = bg_file.filename
            input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
            with open(input_bg_path, "wb") as f:
                shutil.copyfileobj(bg_file.file, f)
            has_bg = True
            if save_to_library:
                shutil.copy2(input_bg_path, os.path.join(LIBRARY_DIR, "photos", bg_filename))
        elif library_bg:
            src_bg = os.path.join(LIBRARY_DIR, "photos", library_bg)
            if os.path.exists(src_bg):
                bg_ext = os.path.splitext(library_bg)[1]
                bg_filename = library_bg
                input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
                shutil.copy2(src_bg, input_bg_path)
                has_bg = True
            
        if not already_downloaded:
            logger.info(f"Novo processamento do YouTube solicitado ({youtube_url.strip()}). Limpando cache anterior...")
            for f_name in os.listdir(cache_dir):
                if f_name.startswith("original_bg"):
                    continue
                f_path = os.path.join(cache_dir, f_name)
                try:
                    if os.path.isfile(f_path):
                        os.remove(f_path)
                    elif os.path.isdir(f_path):
                        shutil.rmtree(f_path)
                except Exception as e:
                    logger.error(f"Erro ao limpar cache: {e}")

            # Baixar o áudio/vídeo do YouTube agora
            input_audio_path, orig_name = download_youtube(youtube_url.strip(), cache_dir)
            ext = os.path.splitext(input_audio_path)[1]

            if save_to_library:
                try:
                    lib_video_dir = os.path.join(LIBRARY_DIR, "videos")
                    os.makedirs(lib_video_dir, exist_ok=True)
                    safe_title = "".join([c for c in orig_name if c.isalnum() or c in ' ._-']).strip() or "youtube_download"
                    shutil.copy2(input_audio_path, os.path.join(lib_video_dir, f"{safe_title}{ext}"))
                except Exception as copy_err:
                    logger.error(f"Erro ao salvar YouTube na biblioteca: {copy_err}")

            cached_meta = {
                "source_type": "youtube",
                "youtube_url": youtube_url.strip(),
                "original_filename": orig_name,
                "audio_filename": orig_name + ext,
                "input_ext": ext,
                "has_bg": has_bg,
                "bg_ext": bg_ext,
                "bg_filename": bg_filename,
                "lyrics_text": lyrics_text or ""
            }
            with open(cache_meta_file, "w", encoding="utf-8") as f:
                json.dump(cached_meta, f, indent=4)
        else:
            # Manter metadados mas atualizar background e letra
            try:
                with open(cache_meta_file, "r", encoding="utf-8") as f:
                    cached_meta = json.load(f)
                cached_meta["has_bg"] = has_bg
                cached_meta["bg_ext"] = bg_ext
                cached_meta["bg_filename"] = bg_filename
                cached_meta["lyrics_text"] = lyrics_text or ""
                with open(cache_meta_file, "w", encoding="utf-8") as f:
                    json.dump(cached_meta, f, indent=4)
            except Exception:
                pass

    elif library_audio:
        import unicodedata
        lib_video_dir = os.path.join(LIBRARY_DIR, "videos")
        lib_audio_path = os.path.join(lib_video_dir, library_audio)
        
        # Busca resiliente se o nome exato com acentos/caracteres especiais falhar
        if not os.path.exists(lib_audio_path):
            log_diagnostic(f"Arquivo exato '{library_audio}' não encontrado no caminho direto. Iniciando busca resiliente...", "WARNING")
            found_file = None
            if os.path.exists(lib_video_dir):
                available = os.listdir(lib_video_dir)
                target_norm = unicodedata.normalize('NFD', library_audio).encode('ascii', 'ignore').decode().lower()
                for fname in available:
                    fname_norm = unicodedata.normalize('NFD', fname).encode('ascii', 'ignore').decode().lower()
                    if fname_norm == target_norm or fname.lower() == library_audio.lower():
                        found_file = fname
                        break
            if found_file:
                log_diagnostic(f"Música encontrada via correspondência resiliente: '{found_file}'", "INFO")
                library_audio = found_file
                lib_audio_path = os.path.join(lib_video_dir, library_audio)
            else:
                avail_list = os.listdir(lib_video_dir) if os.path.exists(lib_video_dir) else []
                err_detail = f"Música '{library_audio}' não encontrada na Biblioteca. Arquivos disponíveis na pasta /data/library/videos: {avail_list}"
                log_diagnostic(err_detail, "ERROR")
                raise HTTPException(status_code=400, detail=err_detail)
            
        orig_name = os.path.splitext(library_audio)[0]
        audio_ext = os.path.splitext(library_audio)[1]
        
        logger.info("Nova música da biblioteca selecionada. Limpando cache anterior...")
        for f_name in os.listdir(cache_dir):
            f_path = os.path.join(cache_dir, f_name)
            try:
                if os.path.isfile(f_path):
                    os.remove(f_path)
                elif os.path.isdir(f_path):
                    shutil.rmtree(f_path)
            except Exception as e:
                logger.error(f"Erro ao limpar cache: {e}")
                
        input_audio_path = os.path.join(cache_dir, f"original_input{audio_ext}")
        shutil.copy2(lib_audio_path, input_audio_path)
        
        input_bg_path = None
        has_bg = False
        bg_ext = None
        bg_filename = None
        
        if bg_file and bg_file.filename:
            bg_ext = os.path.splitext(bg_file.filename)[1]
            bg_filename = bg_file.filename
            input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
            with open(input_bg_path, "wb") as f:
                shutil.copyfileobj(bg_file.file, f)
            has_bg = True
            if save_to_library:
                shutil.copy2(input_bg_path, os.path.join(LIBRARY_DIR, "photos", bg_filename))
        elif library_bg:
            src_bg = os.path.join(LIBRARY_DIR, "photos", library_bg)
            if os.path.exists(src_bg):
                bg_ext = os.path.splitext(library_bg)[1]
                bg_filename = library_bg
                input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
                shutil.copy2(src_bg, input_bg_path)
                has_bg = True

        cached_meta = {
            "original_filename": orig_name,
            "audio_filename": library_audio,
            "input_ext": audio_ext,
            "has_bg": has_bg,
            "bg_ext": bg_ext,
            "bg_filename": bg_filename,
            "lyrics_text": lyrics_text or ""
        }
        with open(cache_meta_file, "w", encoding="utf-8") as f:
            json.dump(cached_meta, f, indent=4)

    elif audio_file and audio_file.filename and audio_file.filename.strip():
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
                logger.error(f"Erro ao limpar cache: {e}")
                
        input_audio_path = os.path.join(cache_dir, f"original_input{audio_ext}")
        with open(input_audio_path, "wb") as f:
            shutil.copyfileobj(audio_file.file, f)
            
        if save_to_library:
            shutil.copy2(input_audio_path, os.path.join(LIBRARY_DIR, "videos", audio_file.filename))
            
        input_bg_path = None
        has_bg = False
        bg_ext = None
        bg_filename = None
        
        if bg_file and bg_file.filename:
            bg_ext = os.path.splitext(bg_file.filename)[1]
            bg_filename = bg_file.filename
            input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
            with open(input_bg_path, "wb") as f:
                shutil.copyfileobj(bg_file.file, f)
            has_bg = True
            if save_to_library:
                shutil.copy2(input_bg_path, os.path.join(LIBRARY_DIR, "photos", bg_filename))
        elif library_bg:
            src_bg = os.path.join(LIBRARY_DIR, "photos", library_bg)
            if os.path.exists(src_bg):
                bg_ext = os.path.splitext(library_bg)[1]
                bg_filename = library_bg
                input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
                shutil.copy2(src_bg, input_bg_path)
                has_bg = True
            
        cached_meta = {
            "original_filename": orig_name,
            "audio_filename": audio_file.filename,
            "input_ext": audio_ext,
            "has_bg": has_bg,
            "bg_ext": bg_ext,
            "bg_filename": bg_filename,
            "lyrics_text": lyrics_text or ""
        }
        with open(cache_meta_file, "w", encoding="utf-8") as f:
            json.dump(cached_meta, f, indent=4)

    else:
        cached_meta = {}
        if os.path.exists(cache_meta_file):
            try:
                with open(cache_meta_file, "r", encoding="utf-8") as f:
                    cached_meta = json.load(f)
            except Exception:
                pass
                
        orig_name = cached_meta.get("original_filename")
        input_ext = cached_meta.get("input_ext")
        
        if not orig_name or not input_ext:
            raise HTTPException(
                status_code=400,
                detail="Nenhum arquivo enviado, nenhuma URL e nenhum cache disponível no servidor."
            )
            
        input_audio_path = os.path.join(cache_dir, f"original_input{input_ext}")
        if not os.path.exists(input_audio_path):
            raise HTTPException(
                status_code=400,
                detail="Arquivos de cache não encontrados. Por favor, envie uma música."
            )
            
        if lyrics_text is not None:
            cached_meta["lyrics_text"] = lyrics_text
            with open(cache_meta_file, "w", encoding="utf-8") as f:
                json.dump(cached_meta, f, indent=4)
                
        if bg_file and bg_file.filename:
            if cached_meta.get("has_bg"):
                old_ext = cached_meta.get("bg_ext", "")
                old_path = os.path.join(cache_dir, f"original_bg{old_ext}")
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
            bg_ext = os.path.splitext(bg_file.filename)[1]
            bg_filename = bg_file.filename
            input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
            with open(input_bg_path, "wb") as f:
                shutil.copyfileobj(bg_file.file, f)
            cached_meta["has_bg"] = True
            cached_meta["bg_ext"] = bg_ext
            cached_meta["bg_filename"] = bg_filename
            with open(cache_meta_file, "w", encoding="utf-8") as f:
                json.dump(cached_meta, f, indent=4)
            if save_to_library:
                shutil.copy2(input_bg_path, os.path.join(LIBRARY_DIR, "photos", bg_filename))
        elif library_bg:
            if cached_meta.get("has_bg"):
                old_ext = cached_meta.get("bg_ext", "")
                old_path = os.path.join(cache_dir, f"original_bg{old_ext}")
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass
            bg_ext = os.path.splitext(library_bg)[1]
            bg_filename = library_bg
            input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
            shutil.copy2(os.path.join(LIBRARY_DIR, "photos", library_bg), input_bg_path)
            cached_meta["has_bg"] = True
            cached_meta["bg_ext"] = bg_ext
            cached_meta["bg_filename"] = bg_filename
            with open(cache_meta_file, "w", encoding="utf-8") as f:
                json.dump(cached_meta, f, indent=4)
        else:
            input_bg_path = None
            if cached_meta.get("has_bg"):
                bg_ext = cached_meta.get("bg_ext")
                input_bg_path = os.path.join(cache_dir, f"original_bg{bg_ext}")
                if not os.path.exists(input_bg_path):
                    input_bg_path = None

    update_state("processing", "Uploading", 5, original_filename=orig_name)
        
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
        keep_first_line_visible,
        youtube_url,
        only_remove_vocals
    )
    
    return {"status": "processing"}

def send_telegram_video_flow(token: str, chat_id: str, video_path: str, orig_name: str):
    """Auxiliar para envio de vídeo para o Telegram em segundo plano (thread dedicada) com tratamento de limite de 50MB."""
    if not token or not chat_id:
        return

    LIMIT_50MB = 50 * 1024 * 1024
    
    # Função auxiliar para copiar vídeo final para a biblioteca de histórico
    def save_to_library_history():
        try:
            lib_history_dir = "/data/library/history"
            os.makedirs(lib_history_dir, exist_ok=True)
            safe_name = "".join([c for c in orig_name if c.isalnum() or c in ' ._-']).strip() or "video_final"
            dest_filename = f"{safe_name}.mp4"
            dest_path = os.path.join(lib_history_dir, dest_filename)
            counter = 1
            while os.path.exists(dest_path):
                dest_filename = f"{safe_name}_{counter}.mp4"
                dest_path = os.path.join(lib_history_dir, dest_filename)
                counter += 1
            shutil.copy2(video_path, dest_path)
            logger.info(f"Vídeo de karaokê {orig_name} salvo automaticamente na biblioteca de histórico: {dest_path}")
            return dest_filename
        except Exception as err:
            logger.error(f"Erro ao salvar vídeo na biblioteca de histórico: {err}")
            return None

    try:
        if os.path.exists(video_path) and os.path.getsize(video_path) > LIMIT_50MB:
            file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
            logger.info(f"O vídeo {orig_name} tem {file_size_mb:.1f}MB, excedendo o limite de 50MB do Telegram.")
            dest_name = save_to_library_history()
            
            msg = (
                f"🎬 <b>Sal0 Karaokê</b>: O vídeo de <b>{orig_name}</b> foi concluído com sucesso!\n\n"
                f"⚠️ O arquivo possui <b>{file_size_mb:.1f}MB</b> (excede o limite de 50MB do Telegram para bots).\n"
                f"💾 Ele foi salvo automaticamente no servidor e já está disponível na sua <b>Biblioteca</b>!"
            )
            send_telegram_notification(token=token, chat_id=chat_id, message=msg)
            return

        # Tentativa de envio para vídeos <= 50MB
        url = f"https://api.telegram.org/bot{token}/sendVideo"
        success = False
        with open(video_path, "rb") as video_file:
            files = {"video": video_file}
            data = {
                "chat_id": chat_id,
                "caption": f"🎥 <b>Sal0 Karaokê</b>: Aqui está o seu vídeo de karaokê pronto para <b>{orig_name}</b>!",
                "parse_mode": "HTML"
            }
            res = requests.post(url, data=data, files=files, timeout=90)
            if res.status_code == 200:
                success = True
                logger.info("Vídeo enviado com sucesso para o Telegram.")
            else:
                logger.error(f"Telegram recusou envio do vídeo: {res.text}")

        if success:
            send_telegram_notification(
                token=token, 
                chat_id=chat_id, 
                message=f"✅ <b>Sal0 Karaokê</b>: Processamento de <b>{orig_name}</b> concluído!"
            )
        else:
            save_to_library_history()
            msg = (
                f"🎬 <b>Sal0 Karaokê</b>: O vídeo de <b>{orig_name}</b> foi concluído com sucesso!\n\n"
                f"⚠️ Não foi possível enviar o vídeo via Telegram. Ele foi salvo no servidor e está disponível na sua <b>Biblioteca</b>."
            )
            send_telegram_notification(token=token, chat_id=chat_id, message=msg)

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
    keep_first_line_visible: bool = False,
    youtube_url: str = None,
    only_remove_vocals: bool = False
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
            f"🎙️ <b>Sal0 Karaokê</b>: Iniciando processamento de <b>{orig_name}</b>..."
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

        # Se for link do YouTube, realiza o download agora em background (se já não estiver no cache)
        if youtube_url and youtube_url.strip():
            already_downloaded = False
            if os.path.exists(cache_meta_file):
                try:
                    with open(cache_meta_file, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if meta.get("youtube_url") == youtube_url.strip():
                            ext = meta.get("input_ext", ".mp4")
                            orig_file = os.path.join(cache_dir, f"original_input{ext}")
                            if os.path.exists(orig_file):
                                already_downloaded = True
                                input_audio_path = orig_file
                                orig_name = meta.get("original_filename", "YouTube Video")
                except Exception:
                    pass

            if not already_downloaded:
                pm.check_cancelled()
                update_state("processing", "Downloading YouTube", 5)
                send_telegram_notification(
                    telegram_token, 
                    telegram_chat_id, 
                    f"🌐 <b>Sal0 Karaokê</b>: Iniciando download do YouTube..."
                )
                
                try:
                    input_audio_path, title = download_youtube(youtube_url, cache_dir)
                    orig_name = title
                    update_state("processing", "Extracting audio", 15, original_filename=orig_name)
                    
                    ext = os.path.splitext(input_audio_path)[1]
                    cached_meta["youtube_url"] = youtube_url
                    cached_meta["original_filename"] = orig_name
                    cached_meta["audio_filename"] = orig_name + ext
                    cached_meta["input_ext"] = ext
                    with open(cache_meta_file, "w", encoding="utf-8") as f:
                        import json
                        json.dump(cached_meta, f, indent=4)
                        
                    send_telegram_notification(
                        telegram_token, 
                        telegram_chat_id, 
                        f"📥 <b>Sal0 Karaokê</b>: Download concluído! <b>{orig_name}</b>"
                    )
                except Exception as e:
                    logger.error(f"Erro ao baixar do YouTube: {e}")
                    raise RuntimeError(f"Falha ao baixar vídeo do YouTube: {e}")
            else:
                logger.info("Reaproveitando download do YouTube do cache.")
                
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

        # Se for um novo arquivo ou URL do YouTube, garanta que arquivos intermediários da música anterior não existam
        if youtube_url or not os.path.exists(os.path.join(cache_dir, "original_converted.wav")):
            for inter_file in ["vocals.wav", "instrumental.wav", "transcribed_segments.json"]:
                inter_path = os.path.join(cache_dir, inter_file)
                if os.path.exists(inter_path):
                    try:
                        os.remove(inter_path)
                    except Exception as e:
                        pass

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
                send_telegram_notification(telegram_token, telegram_chat_id, "🎵 <b>Sal0 Karaokê</b>: Extraindo áudio (15%)")
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
                send_telegram_notification(telegram_token, telegram_chat_id, "✂️ <b>Sal0 Karaokê</b>: Separando áudio (40%)")
                with tempfile.TemporaryDirectory() as demucs_tmp:
                    v_tmp, i_tmp = separate_vocals(converted_wav, demucs_tmp, update_callback=update_state)
                    shutil.move(v_tmp, vocals_wav)
                    shutil.move(i_tmp, instrumental_wav)
                    
            pm.check_cancelled()

            # Se only_remove_vocals estiver ativo, pulamos transcrição e legenda, indo direto para renderização
            if only_remove_vocals:
                pm.check_cancelled()
                update_state("processing", "Rendering final video", 95)
                send_telegram_notification(
                    telegram_token, 
                    telegram_chat_id, 
                    f"🎬 <b>Sal0 Karaokê</b>: Renderizando vídeo sem a voz do cantor (95%)"
                )
                
                # Forçar o uso do vídeo original enviado
                render_karaoke_video(
                    instrumental_path=instrumental_wav,
                    ass_path=None,
                    output_mp4_path=final_mp4_path,
                    background_image_path=None,
                    original_video_path=input_audio_path,
                    background_mode="original_video"
                )
                
                pm.check_cancelled()
                update_state("processing", "Cleaning temporary files", 98)
                update_state("done", "Done", 100, result_file=final_mp4_path)
                logger.info("Pipeline concluído: Vocais removidos do vídeo original com sucesso.")
                
                processing_lock.release()
                
                if telegram_token and telegram_chat_id:
                    threading.Thread(
                        target=send_telegram_video_flow,
                        args=(telegram_token, telegram_chat_id, final_mp4_path, orig_name),
                        daemon=True
                    ).start()
                return
            
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
                send_telegram_notification(telegram_token, telegram_chat_id, f"✍️ <b>Sal0 Karaokê</b>: Transcrevendo voz ({whisper_model}) (70%)")
                
                transcribe_audio = vocals_wav if transcribe_source == "vocals" else converted_wav
                logger.info(f"Fonte de transcrição escolhida: {transcribe_audio} (Modo: {transcribe_source})")
                
                # Verificar se o modelo Whisper está baixado para informar o usuário na 1ª vez
                folder_name = f"models--Systran--faster-whisper-{whisper_model}"
                model_path = os.path.join("/data/output/models/whisper", folder_name)
                if not os.path.exists(model_path):
                    update_state("processing", f"Baixando Modelo de IA Whisper {whisper_model} (Download único de ~1.5GB)...", 65)
                
                quality_preset = "max_quality" if whisper_model == "large-v3" else "standard"
                segments = transcribe_vocals(transcribe_audio, model_size=whisper_model, initial_prompt=lyrics_text, quality_mode=quality_preset)
                
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
                    f"⚠️ <b>Sal0 Karaokê</b>: A transcrição de <b>{orig_name}</b> está pronta para correção! "
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
            
            # Passo 4: Gerar legendas ASS com efeitos de karaokê
            update_state("processing", "Generating subtitles", 80)
            send_telegram_notification(telegram_token, telegram_chat_id, "📝 <b>Sal0 Karaokê</b>: Gerando legenda (80%)")
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
            send_telegram_notification(telegram_token, telegram_chat_id, "🎬 <b>Sal0 Karaokê</b>: Renderizando vídeo (95%)")
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
            logger.info("Pipeline de Karaokê Maker concluído com sucesso!")
            
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
                f"❌ <b>Sal0 Karaokê</b>: Falha ao processar <b>{orig_name}</b>. Erro: {e}"
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
    """Endpoint para baixar o arquivo final de vídeo karaokê."""
    file_path = "/data/output/final_karaoke.mp4"
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404, 
            detail="Arquivo de vídeo não encontrado. Por favor, processe um áudio primeiro."
        )
    # Recuperar o nome original com sufixo _karaokê
    with state_lock:
        orig_name = state.get("original_filename", "final")
    download_name = f"{orig_name}_karaokê.mp4"
    return FileResponse(
        file_path, 
        media_type="video/mp4", 
        filename=download_name
    )
