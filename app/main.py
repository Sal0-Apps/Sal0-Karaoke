import os
import uuid
import shutil
import logging
import tempfile
import threading
import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
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
def get_models_status():
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
def start_model_download(req: ModelDownloadRequest):
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

def load_profiles() -> dict:
    """Carrega os perfis do arquivo JSON ou inicializa com valores padrão se não existir."""
    default_profiles = {
        "Padrão": {
            "whisper_model": "medium",
            "font_size": 32,
            "text_color": "#00FFFF",
            "text_position": "bottom",
            "telegram_token": "",
            "telegram_chat_id": ""
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
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar arquivo de perfis: {e}")
        return default_profiles

@app.get("/api/profiles")
def get_profiles():
    """Retorna todos os perfis salvos."""
    return load_profiles()

@app.post("/api/profiles")
def save_profile(profile: ProfileModel):
    """Salva ou atualiza um perfil de uso."""
    profiles = load_profiles()
    profiles[profile.name] = {
        "whisper_model": profile.whisper_model,
        "font_size": profile.font_size,
        "text_color": profile.text_color,
        "text_position": profile.text_position,
        "telegram_token": profile.telegram_token,
        "telegram_chat_id": profile.telegram_chat_id
    }
    try:
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            import json
            json.dump(profiles, f, indent=4, ensure_ascii=False)
        return {"status": "success", "profiles": profiles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar perfil em disco: {e}")

@app.delete("/api/profiles/{name}")
def delete_profile(name: str):
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

@app.get("/", response_class=HTMLResponse)
def read_index():
    """Serve a interface gráfica web da aplicação."""
    # Retorna o arquivo de template HTML compilado com Jinja2
    # Como não temos variáveis dinâmicas de renderização inicial, passamos apenas o contexto vazio
    return templates.TemplateResponse("index.html", {"request": {}})

@app.get("/api/status")
def get_status():
    """Retorna o progresso atual do pipeline para pooling da interface web."""
    with state_lock:
        return state

@app.post("/api/process")
def process_karaoke(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
    bg_file: UploadFile = File(None),
    whisper_model: str = Form("medium"),
    font_size: int = Form(32),
    text_color: str = Form("#00FFFF"),
    text_position: str = Form("bottom")
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

    # 2. Resetar e preparar o estado para processamento
    orig_name = os.path.splitext(audio_file.filename)[0]
    update_state("processing", "Uploading", 5, original_filename=orig_name)
    
    # Criar uma pasta segura para uploads temporários no diretório /tmp do SO
    upload_dir = os.path.join(tempfile.gettempdir(), "karaoke_uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    # Salvar arquivo de áudio/vídeo enviado
    audio_ext = os.path.splitext(audio_file.filename)[1]
    input_audio_path = os.path.join(upload_dir, f"{uuid.uuid4()}{audio_ext}")
    
    logger.info(f"Salvando arquivo de áudio carregado em: {input_audio_path}")
    with open(input_audio_path, "wb") as f:
        shutil.copyfileobj(audio_file.file, f)
        
    # Salvar imagem de fundo se foi enviada
    input_bg_path = None
    if bg_file and bg_file.filename:
        bg_ext = os.path.splitext(bg_file.filename)[1]
        input_bg_path = os.path.join(upload_dir, f"{uuid.uuid4()}{bg_ext}")
        logger.info(f"Salvando imagem de fundo carregada em: {input_bg_path}")
        with open(input_bg_path, "wb") as f:
            shutil.copyfileobj(bg_file.file, f)
            
    # 3. Adicionar tarefa na fila de execução de segundo plano síncrona
    background_tasks.add_task(
        run_pipeline, 
        input_audio_path, 
        input_bg_path, 
        whisper_model,
        font_size,
        text_color,
        text_position
    )
    
    return {"status": "processing"}
    
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
    text_position: str = "bottom"
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

        # Criar diretório temporário para todo o processamento intermediário (Demucs, Whisper, ASS)
        with tempfile.TemporaryDirectory() as tmpdir:
            logger.info(f"Diretório de trabalho temporário criado: {tmpdir}")
            
            # Passo 1: Extrair / Converter áudio para WAV PCM
            update_state("processing", "Extracting audio", 15)
            send_telegram_notification(telegram_token, telegram_chat_id, "🎵 <b>Sal0 karaoke</b>: Extraindo áudio (15%)")
            converted_wav = os.path.join(tmpdir, "original_converted.wav")
            extract_audio(input_audio_path, converted_wav)
            
            # Passo 2: Separar vocais e instrumental via Demucs
            update_state("processing", "Separating vocals", 40)
            send_telegram_notification(telegram_token, telegram_chat_id, "✂️ <b>Sal0 karaoke</b>: Separando áudio (40%)")
            vocals_wav, instrumental_wav = separate_vocals(converted_wav, tmpdir)
            
            # Passo 3: Transcrever vocais com Whisper selecionado
            update_state("processing", "Transcribing vocals", 70)
            send_telegram_notification(telegram_token, telegram_chat_id, f"✍️ <b>Sal0 karaoke</b>: Transcrevendo voz ({whisper_model}) (70%)")
            segments = transcribe_vocals(vocals_wav, model_size=whisper_model)
            
            if not segments:
                raise ValueError("Nenhum vocal detectado ou transcrição vazia.")
            
            # Passo 4: Gerar legendas ASS com efeitos de karaoke
            update_state("processing", "Generating subtitles", 80)
            send_telegram_notification(telegram_token, telegram_chat_id, "📝 <b>Sal0 karaoke</b>: Gerando legenda (80%)")
            ass_path = os.path.join(tmpdir, "karaoke.ass")
            generate_ass_karaoke(
                segments=segments, 
                output_ass_path=ass_path,
                font_size=font_size,
                text_color_hex=text_color,
                text_position=text_position
            )
            
            # Passo 5: Renderizar o vídeo final
            update_state("processing", "Rendering final video", 95)
            send_telegram_notification(telegram_token, telegram_chat_id, "🎬 <b>Sal0 karaoke</b>: Renderizando vídeo (95%)")
            render_karaoke_video(
                instrumental_path=instrumental_wav,
                ass_path=ass_path,
                output_mp4_path=final_mp4_path,
                background_image_path=input_bg_path
            )
            
            # Salvar opcionalmente a legenda ASS final gerada junto com o MP4
            shutil.copy(ass_path, final_ass_path)
            
            # Passo 6: Limpar arquivos de upload de entrada
            update_state("processing", "Cleaning temporary files", 98)
            try:
                if os.path.exists(input_audio_path):
                    os.remove(input_audio_path)
                if input_bg_path and os.path.exists(input_bg_path):
                    os.remove(input_bg_path)
            except Exception as ex:
                logger.warning(f"Falha ao deletar arquivos originais carregados: {ex}")

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
        update_state("error", "Error", 0, error_message=str(e))
        send_telegram_notification(
            telegram_token, 
            telegram_chat_id, 
            f"❌ <b>Sal0 karaoke</b>: Falha ao processar <b>{orig_name}</b>. Erro: {e}"
        )
        
        # Limpar arquivos de upload em caso de erro
        try:
            if os.path.exists(input_audio_path):
                os.remove(input_audio_path)
            if input_bg_path and os.path.exists(input_bg_path):
                os.remove(input_bg_path)
        except Exception as ex:
            logger.error(f"Erro ao limpar arquivos de upload após erro: {ex}")
            
    finally:
        # Liberar o processador de forma segura caso ainda esteja bloqueado
        if processing_lock.locked():
            try:
                processing_lock.release()
            except RuntimeError:
                pass

@app.get("/api/download")
def download_file():
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
