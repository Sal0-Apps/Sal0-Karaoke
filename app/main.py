import socket
socket.setdefaulttimeout(120)  # Timeout de 120s para impedir travamentos de socket em downloads de IA
import os
import uuid
import shutil
import logging
import logging.handlers
import mimetypes
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import re
import difflib
import json
import hashlib
import unicodedata
from urllib.parse import quote
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Header, Depends, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, Response, StreamingResponse
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

RUNTIME_LOG_FILE = "/data/output/app_runtime.log"
try:
    os.makedirs(os.path.dirname(RUNTIME_LOG_FILE), exist_ok=True)
    if not any(getattr(handler, "baseFilename", None) == RUNTIME_LOG_FILE for handler in logging.getLogger().handlers):
        runtime_handler = logging.handlers.RotatingFileHandler(
            RUNTIME_LOG_FILE,
            maxBytes=2 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8"
        )
        runtime_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(runtime_handler)
except Exception:
    # O stdout do contêiner continua disponível mesmo se o volume ainda não estiver pronto.
    pass

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


def validate_new_credentials(username: str, password: str):
    if not re.fullmatch(r"[\w.@-]{3,40}", username or "", re.UNICODE):
        raise HTTPException(
            status_code=400,
            detail="O usuário deve ter de 3 a 40 caracteres e usar apenas letras, números, ponto, hífen ou sublinhado."
        )
    if len(password or "") < 8:
        raise HTTPException(status_code=400, detail="A senha deve ter pelo menos 8 caracteres.")

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

    username = session.get("username")
    user_record = users.get(username)
    if not user_record:
        sessions.pop(active_token, None)
        save_sessions(sessions)
        raise HTTPException(status_code=401, detail="Usuário removido ou sessão inválida.")

    # A permissão atual vem do cadastro, não de uma sessão antiga.
    current_role = user_record.get("role", "user")
    if session.get("role") != current_role:
        session["role"] = current_role
        sessions[active_token] = session
        save_sessions(sessions)
    return {"username": username, "role": current_role, "created_at": session.get("created_at")}


USER_DATA_ROOT = "/data/user_data"
LEGACY_LIBRARY_DIR = "/data/library"
LEGACY_CACHE_DIR = "/data/cache"
LEGACY_OUTPUT_DIR = "/data/output"


def is_admin(user: dict) -> bool:
    return user.get("role") in {"admin", "setup"}


def require_admin(user: dict):
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Apenas administradores podem acessar esta função.")


def user_from_username(username: str) -> dict | None:
    record = load_users().get(username)
    if not record:
        return None
    return {"username": username, "role": record.get("role", "user")}


def user_storage_key(username: str) -> str:
    """Cria um nome de pasta estável sem confiar no texto informado pelo usuário."""
    return hashlib.sha256((username or "user").encode("utf-8")).hexdigest()[:24]


def get_user_paths(user: dict) -> dict:
    """Mantém os dados legados com o admin e isola cada usuário comum."""
    if is_admin(user):
        paths = {
            "library": LEGACY_LIBRARY_DIR,
            "cache": LEGACY_CACHE_DIR,
            "output": LEGACY_OUTPUT_DIR,
        }
    else:
        root = os.path.join(USER_DATA_ROOT, user_storage_key(user.get("username", "user")))
        paths = {
            "library": os.path.join(root, "library"),
            "cache": os.path.join(root, "cache"),
            "output": os.path.join(root, "output"),
        }

    for section in ("videos", "photos", "history"):
        os.makedirs(os.path.join(paths["library"], section), exist_ok=True)
    os.makedirs(paths["cache"], exist_ok=True)
    os.makedirs(paths["output"], exist_ok=True)
    return paths


def config_path(user: dict, filename: str) -> str:
    return os.path.join(get_user_paths(user)["output"], filename)


def current_task_owned_by(user: dict) -> bool:
    return state.get("owner_username") == user.get("username")


def require_task_control(user: dict):
    if not (is_admin(user) or current_task_owned_by(user)):
        raise HTTPException(status_code=403, detail="Esta tarefa pertence a outro usuário.")

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
    "stage_progress": None,    # progresso interno opcional da etapa atual
    "stage_detail": "",        # explicação curta da etapa, exibida sem uma segunda barra
    "error_message": "",
    "result_file": None,
    "original_filename": "final",
    "owner_username": None,
    "owner_role": None,
    "history_filename": None,
    "public_download_token": None
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
    """Normaliza uma palavra para comparar a letra sem perder sua grafia original."""
    decomposed = unicodedata.normalize("NFKD", str(w))
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r'[^\w]', '', without_accents).casefold()

def align_lyrics(official_lyrics_text: str, transcribed_segments: list[dict]) -> list[dict]:
    """Usa a letra como guia de grafia sem criar ou mover timestamps.

    Refrões repetidos tornam inseguro reconstruir a linha do tempo a partir de
    uma comparação textual global. Por isso, somente palavras já confirmadas
    pelo Whisper recebem a grafia da letra oficial; versos ausentes permanecem
    ausentes e toda a estrutura temporal original é preservada.
    """
    official_words = []
    official_line_ends = set()
    for lyric_line in official_lyrics_text.splitlines():
        line_words = [word for word in lyric_line.split() if clean_word(word)]
        if not line_words:
            continue
        official_words.extend(line_words)
        official_line_ends.add(len(official_words) - 1)
    if not official_words or not transcribed_segments:
        return transcribed_segments

    guided_segments = []
    transcribed_words = []
    for source_segment in transcribed_segments:
        copied_words = [dict(word) for word in source_segment.get("words", [])]
        for copied_word in copied_words:
            copied_word.pop("lyric_line_break", None)
        copied_segment = {**source_segment, "words": copied_words}
        guided_segments.append(copied_segment)
        for copied_word in copied_words:
            if clean_word(copied_word.get("word", "")):
                transcribed_words.append(copied_word)

    if not transcribed_words:
        return transcribed_segments

    official_clean = [clean_word(word) for word in official_words]
    transcribed_clean = [clean_word(word.get("word", "")) for word in transcribed_words]
    matcher = difflib.SequenceMatcher(None, official_clean, transcribed_clean, autojunk=False)
    matched = 0

    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            official_index = block.a + offset
            official_word = official_words[official_index].strip()
            target_word = transcribed_words[block.b + offset]
            current_text = str(target_word.get("word", ""))
            leading_space = current_text[:len(current_text) - len(current_text.lstrip())]
            trailing_space = current_text[len(current_text.rstrip()):]
            target_word["word"] = f"{leading_space}{official_word}{trailing_space}"
            if official_index in official_line_ends:
                target_word["lyric_line_break"] = True
            matched += 1

    for segment in guided_segments:
        if segment.get("words"):
            segment["text"] = "".join(word.get("word", "") for word in segment["words"]).strip()

    logger.info(
        "Letra guia aplicada à grafia de %s/%s palavras; todos os timestamps do Whisper foram preservados.",
        matched,
        len(transcribed_words),
    )
    return guided_segments

def update_state(
    status: str,
    step: str,
    progress: int,
    error_message: str = "",
    result_file: str = None,
    original_filename: str = None,
    owner_username: str = None,
    owner_role: str = None,
    history_filename: str = None,
    public_download_token: str = None,
    stage_progress: int | None = None,
    stage_detail: str = ""
):
    """Atualiza o estado global da aplicação de forma thread-safe e persiste no disco."""
    with state_lock:
        state["status"] = status
        state["step"] = step
        state["progress"] = progress
        state["stage_progress"] = stage_progress
        state["stage_detail"] = stage_detail
        state["error_message"] = error_message
        state["result_file"] = result_file
        if original_filename is not None:
            state["original_filename"] = original_filename
        if owner_username is not None:
            state["owner_username"] = owner_username
            state["history_filename"] = None
            state["public_download_token"] = None
        if owner_role is not None:
            state["owner_role"] = owner_role
        if history_filename is not None:
            state["history_filename"] = history_filename
        if public_download_token is not None:
            state["public_download_token"] = public_download_token

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
                if saved_state.get("status") in {"processing", "downloading", "waiting_for_user_correction", "awaiting_review"}:
                    state.update(saved_state)
                    orig_name = saved_state.get("original_filename", "vídeo")
                    logger.warning("Detecção de reinicialização abrupta (possível OOM ou queda)!")

                    state["status"] = "error"
                    state["step"] = "Interrupted"
                    state["progress"] = 0
                    state["error_message"] = "O servidor foi interrompido inesperadamente (possivelmente ficou sem memória RAM ou o container reiniciou)."

                    # Salvar o estado de erro persistente
                    with open(STATE_FILE, "w", encoding="utf-8") as sf:
                        json.dump(state, sf, indent=4)

                    owner = user_from_username(saved_state.get("owner_username", ""))
                    for target in get_notification_targets(owner):
                        send_telegram_notification(
                            target["telegram_token"],
                            target["telegram_chat_id"],
                            f"⚠️ <b>Sal0 Karaokê</b>: O servidor foi reiniciado inesperadamente ou ficou sem memória RAM (OOM) enquanto processava <b>{orig_name}</b>!"
                        )
                else:
                    state.update(saved_state)
        except Exception as e:
            logger.error(f"Erro ao carregar estado inicial no startup: {e}")


def save_video_to_history(video_path: str, orig_name: str, library_dir: str) -> str:
    """Salva uma cópia permanente no histórico do dono da tarefa."""
    if not video_path or not os.path.exists(video_path):
        return None
    try:
        lib_history_dir = os.path.join(library_dir, "history")
        os.makedirs(lib_history_dir, exist_ok=True)
        safe_name = "".join([c for c in orig_name if c.isalnum() or c in ' ._-']).strip() or "video_karaoke"
        if not safe_name.lower().endswith(".mp4"):
            dest_filename = f"{safe_name}.mp4"
        else:
            dest_filename = safe_name
            safe_name = os.path.splitext(safe_name)[0]

        dest_path = os.path.join(lib_history_dir, dest_filename)
        counter = 1
        while os.path.exists(dest_path):
            dest_filename = f"{safe_name}_{counter}.mp4"
            dest_path = os.path.join(lib_history_dir, dest_filename)
            counter += 1

        shutil.copy2(video_path, dest_path)
        logger.info(f"Vídeo de karaokê '{orig_name}' salvo com sucesso no Histórico: {dest_path}")
        return dest_filename
    except Exception as err:
        logger.error(f"Erro ao salvar vídeo no histórico: {err}")
        return None


def save_result_metadata(output_dir: str, original_filename: str, history_filename: str):
    try:
        with open(os.path.join(output_dir, "result_meta.json"), "w", encoding="utf-8") as file:
            json.dump({
                "original_filename": original_filename,
                "history_filename": history_filename,
                "completed_at": time.time()
            }, file, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("Não foi possível salvar metadados do resultado: %s", exc)

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

# Bot do Telegram por usuário; o arquivo legado continua sendo o bot do administrador.
TELEGRAM_FILE = "/data/output/telegram.json"

class TelegramModel(BaseModel):
    telegram_token: str
    telegram_chat_id: str

def telegram_file_for_user(user: dict) -> str:
    return TELEGRAM_FILE if is_admin(user) else config_path(user, "telegram.json")


def load_telegram_config(user: dict = None) -> dict:
    """Carrega somente o bot pertencente ao usuário informado."""
    if not user:
        return {"telegram_token": "", "telegram_chat_id": ""}
    telegram_file = telegram_file_for_user(user)
    if not os.path.exists(telegram_file):
        return {"telegram_token": "", "telegram_chat_id": ""}
    try:
        with open(telegram_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar configurações do Telegram: {e}")
        return {"telegram_token": "", "telegram_chat_id": ""}

def get_notification_targets(owner: dict | None) -> list[dict]:
    """Notifica o bot pessoal do dono e todos os administradores configurados."""
    target_users = []
    if owner:
        target_users.append(owner)
    for username, record in load_users().items():
        if record.get("role") == "admin" and username != (owner or {}).get("username"):
            target_users.append({"username": username, "role": "admin"})

    targets = []
    seen = set()
    for target_user in target_users:
        config = load_telegram_config(target_user)
        token = str(config.get("telegram_token") or "").strip()
        chat_id = str(config.get("telegram_chat_id") or "").strip()
        key = (token, chat_id)
        if token and chat_id and key not in seen:
            seen.add(key)
            targets.append({"telegram_token": token, "telegram_chat_id": chat_id})
    return targets


def notify_targets(targets: list[dict], message: str):
    for target in targets:
        send_telegram_notification(target["telegram_token"], target["telegram_chat_id"], message)


@app.get("/api/telegram")
def get_telegram_config(current_user: dict = Depends(get_current_user)):
    """Retorna apenas o bot pessoal da conta autenticada."""
    config = load_telegram_config(current_user)
    # Mascarar token parcialmente na resposta para não expor o valor completo
    token = config.get("telegram_token", "")
    if token and len(token) > 8:
        config["telegram_token"] = token[:6] + "***" + token[-4:]
    return config

@app.post("/api/telegram")
def save_telegram_config(config: TelegramModel, current_user: dict = Depends(get_current_user)):
    """Salva apenas o bot pessoal da conta autenticada."""
    try:
        telegram_file = telegram_file_for_user(current_user)
        previous = load_telegram_config(current_user)
        submitted_token = config.telegram_token.strip()
        if "***" in submitted_token:
            submitted_token = previous.get("telegram_token", "")
        os.makedirs(os.path.dirname(telegram_file), exist_ok=True)
        with open(telegram_file, "w", encoding="utf-8") as f:
            json.dump({
                "telegram_token": submitted_token,
                "telegram_chat_id": config.telegram_chat_id.strip()
            }, f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar configurações do Telegram: {e}")

# Gerenciamento de Configuração de IP/URL Externa
EXTERNAL_URL_FILE = "/data/output/external_url.json"

class ExternalUrlModel(BaseModel):
    external_url: str


EASY_MODE_FILE = "/data/output/easy_mode.json"
EASY_MODE_DEFAULTS = {
    "enabled": True,
    "whisper_model": "large-v3-turbo",
    "font_size": 50,
    "transcription_preset": "difficult",
    "transcribe_source": "original",
    "show_next_line_preview": True,
    "show_instrumental": True,
}


class EasyModeModel(BaseModel):
    enabled: bool = True
    whisper_model: str = "large-v3-turbo"
    font_size: int = 50
    transcription_preset: str = "difficult"
    transcribe_source: str = "original"
    show_next_line_preview: bool = True
    show_instrumental: bool = True


def normalize_easy_mode_config(config: dict | None = None) -> dict:
    normalized = {**EASY_MODE_DEFAULTS, **(config or {})}
    if normalized["whisper_model"] not in {"large-v3-turbo", "large-v3", "medium", "small", "tiny"}:
        normalized["whisper_model"] = EASY_MODE_DEFAULTS["whisper_model"]
    if normalized["transcription_preset"] not in {"karaoke", "continuous", "difficult", "fast"}:
        normalized["transcription_preset"] = EASY_MODE_DEFAULTS["transcription_preset"]
    if normalized["transcribe_source"] not in {"original", "vocals"}:
        normalized["transcribe_source"] = EASY_MODE_DEFAULTS["transcribe_source"]
    normalized["font_size"] = max(24, min(72, int(normalized.get("font_size", 50))))
    normalized["enabled"] = bool(normalized.get("enabled", True))
    normalized["show_next_line_preview"] = bool(normalized.get("show_next_line_preview", True))
    normalized["show_instrumental"] = bool(normalized.get("show_instrumental", True))
    return normalized


def load_easy_mode_config() -> dict:
    if not os.path.exists(EASY_MODE_FILE):
        return dict(EASY_MODE_DEFAULTS)
    try:
        with open(EASY_MODE_FILE, "r", encoding="utf-8") as file:
            return normalize_easy_mode_config(json.load(file))
    except Exception as exc:
        logger.warning("Nao foi possivel carregar o Modo Facil: %s", exc)
        return dict(EASY_MODE_DEFAULTS)


@app.get("/api/easy-mode")
def get_easy_mode_config(current_user: dict = Depends(get_current_user)):
    return load_easy_mode_config()


@app.post("/api/easy-mode")
def save_easy_mode_config(config: EasyModeModel, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    normalized = normalize_easy_mode_config(config.dict())
    try:
        os.makedirs(os.path.dirname(EASY_MODE_FILE), exist_ok=True)
        with open(EASY_MODE_FILE, "w", encoding="utf-8") as file:
            json.dump(normalized, file, indent=4, ensure_ascii=False)
        return {"status": "success", "config": normalized}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar o Modo Facil: {exc}")

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
    require_admin(current_user)
    return load_external_url_config()

@app.post("/api/external_url")
def save_external_url_config(config: ExternalUrlModel, current_user: dict = Depends(get_current_user)):
    """Endpoint para salvar a URL/IP externo."""
    require_admin(current_user)
    try:
        external_url = config.external_url.strip().rstrip("/")
        if external_url and not re.match(r"^https?://[^\s]+$", external_url, re.IGNORECASE):
            raise HTTPException(status_code=400, detail="Informe uma URL completa iniciada por http:// ou https://.")
        os.makedirs(os.path.dirname(EXTERNAL_URL_FILE), exist_ok=True)
        with open(EXTERNAL_URL_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "external_url": external_url
            }, f, indent=4, ensure_ascii=False)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar URL externa: {e}")


# Gerenciamento de Downloads de Modelos Whisper em Background
class ModelDownloadRequest(BaseModel):
    model_size: str = None
    model: str = None


yt_preset_statuses = {}


def youtube_status_key(user: dict, kind: str) -> str:
    return f"{user_storage_key(user.get('username', 'user'))}:{kind}"


def get_youtube_status(user: dict, kind: str) -> dict:
    return yt_preset_statuses.get(
        youtube_status_key(user, kind),
        {"status": "idle", "progress": 0, "title": "", "filename": "", "error": None}
    )

@app.get("/api/youtube-preset-status/audio")
def get_yt_preset_audio_status(current_user: dict = Depends(get_current_user)):
    return get_youtube_status(current_user, "audio")

@app.get("/api/youtube-preset-status/bg")
def get_yt_preset_bg_status(current_user: dict = Depends(get_current_user)):
    return get_youtube_status(current_user, "background")

class YouTubePresetModel(BaseModel):
    youtube_url: str


@app.post("/api/youtube/metadata")
def get_youtube_metadata(
    data: YouTubePresetModel,
    current_user: dict = Depends(get_current_user)
):
    """Identifica o título sem baixar o vídeo, para orientar a busca de letra."""
    url = (data.youtube_url or "").strip()
    if len(url) > 2048 or not re.match(r"^https?://", url, re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Informe uma URL válida do YouTube.")

    try:
        import yt_dlp
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": 10,
        }
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        title = str((info or {}).get("title") or "").strip()
        if not title:
            raise HTTPException(status_code=404, detail="Não foi possível identificar o título desse vídeo.")
        track = str((info or {}).get("track") or "").strip()
        artist = str((info or {}).get("artist") or (info or {}).get("creator") or "").strip()
        lyrics_query = f"{artist} - {track}" if artist and track else title
        return {
            "title": title,
            "lyrics_query": lyrics_query,
            "duration": (info or {}).get("duration"),
            "uploader": str((info or {}).get("uploader") or "").strip(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.info("Não foi possível identificar metadados do YouTube: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Não foi possível identificar esse vídeo agora.")


model_download_status = {
    "large-v3-turbo": {"status": "idle", "progress": 0, "error": None},
    "medium": {"status": "idle", "progress": 0, "error": None},
    "small": {"status": "idle", "progress": 0, "error": None},
    "tiny": {"status": "idle", "progress": 0, "error": None},
    "large-v3": {"status": "idle", "progress": 0, "error": None}
}

def resolve_whisper_repo(model_size: str) -> str:
    """Mapeia os 5 modelos suportados para seus repositórios no Hugging Face (Sal0 Karaoke v4.6.1)."""
    mapping = {
        "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo",
        "medium": "Systran/faster-whisper-medium",
        "small": "Systran/faster-whisper-small",
        "tiny": "Systran/faster-whisper-tiny",
        "large-v3": "Systran/faster-whisper-large-v3"
    }
    return mapping.get(model_size.lower().strip(), model_size)

def get_model_local_dir(model_size: str) -> str:
    """Retorna o diretório local válido contendo os pesos reais (model.bin com tamanho válido) do modelo Whisper."""
    key = model_size.lower().strip()

    # Tamanho mínimo exigido em bytes para garantir que o modelo não está incompleto
    min_size_bytes = 300 * 1024 * 1024  # 300 MB padrão (para medium, large, turbo)
    if "tiny" in key:
        min_size_bytes = 30 * 1024 * 1024   # 30 MB
    elif "small" in key:
        min_size_bytes = 150 * 1024 * 1024  # 150 MB

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
                        for f in files:
                            if f in ["model.bin", "model.safetensors", "pytorch_model.bin", "model.pt"]:
                                fpath = os.path.join(r, f)
                                try:
                                    if os.path.getsize(fpath) >= min_size_bytes:
                                        return r
                                except Exception:
                                    pass
        except Exception as e:
            logger.warning(f"Erro ao verificar modelo em {root}: {e}")
    return None

def is_model_downloaded(model_size: str) -> bool:
    """Verifica nos diretórios locais se um dos 5 modelos Whisper já foi baixado com pesos válidos no disco."""
    return get_model_local_dir(model_size) is not None

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
    require_admin(current_user)
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

def run_youtube_download_bg(url: str, owner: dict):
    status_key = youtube_status_key(owner, "audio")
    paths = get_user_paths(owner)
    cache_dir = paths["cache"]
    os.makedirs(cache_dir, exist_ok=True)
    cache_meta_file = os.path.join(cache_dir, "cache_meta.json")

    yt_preset_statuses[status_key] = {"status": "downloading", "progress": 15, "title": "Conectando ao YouTube...", "filename": "", "error": None}

    try:
        # Limpar áudios e segmentos legados da música anterior
        for old_f in ["original_converted.wav", "vocals.wav", "instrumental.wav", "transcribed_segments.json"]:
            old_p = os.path.join(cache_dir, old_f)
            if os.path.exists(old_p):
                try:
                    os.remove(old_p)
                except Exception:
                    pass

        input_audio_path, title = download_youtube(url, cache_dir)
        ext = os.path.splitext(input_audio_path)[1]

        yt_preset_statuses[status_key]["title"] = title
        yt_preset_statuses[status_key]["progress"] = 70

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

        dest_filename = os.path.basename(input_audio_path)
        try:
            lib_video_dir = os.path.join(paths["library"], "videos")
            os.makedirs(lib_video_dir, exist_ok=True)
            safe_title = "".join([c for c in title if c.isalnum() or c in ' ._-']).strip() or "youtube_download"
            dest_filename = f"{safe_title}{ext}"
            dest_file = os.path.join(lib_video_dir, dest_filename)
            shutil.copy2(input_audio_path, dest_file)
            logger.info(f"Vídeo do YouTube adicionado à biblioteca: {dest_file}")
        except Exception as copy_err:
            logger.error(f"Erro ao salvar vídeo do YouTube na biblioteca: {copy_err}")

        yt_preset_statuses[status_key] = {
            "status": "done",
            "progress": 100,
            "title": title,
            "filename": dest_filename,
            "error": None
        }
    except Exception as e:
        logger.error(f"Erro no download do YouTube em background: {e}")
        yt_preset_statuses[status_key] = {
            "status": "error",
            "progress": 0,
            "title": "",
            "filename": "",
            "error": str(e)
        }

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

def run_bg_youtube_download_bg(url: str, owner: dict):
    status_key = youtube_status_key(owner, "background")
    paths = get_user_paths(owner)
    cache_dir = paths["cache"]
    os.makedirs(cache_dir, exist_ok=True)

    yt_preset_statuses[status_key] = {"status": "downloading", "progress": 15, "title": "Conectando ao YouTube...", "filename": "", "error": None}

    try:
        no_audio_path, title = download_bg_youtube(url, cache_dir)
        ext = os.path.splitext(no_audio_path)[1]

        yt_preset_statuses[status_key]["title"] = title
        yt_preset_statuses[status_key]["progress"] = 70

        dest_filename = os.path.basename(no_audio_path)
        try:
            lib_photos_dir = os.path.join(paths["library"], "photos")
            os.makedirs(lib_photos_dir, exist_ok=True)
            safe_title = "".join([c for c in title if c.isalnum() or c in ' ._-']).strip() or "fundo_youtube"
            dest_filename = f"{safe_title}_sem_audio{ext}"
            dest_file = os.path.join(lib_photos_dir, dest_filename)
            shutil.copy2(no_audio_path, dest_file)
            logger.info(f"Vídeo de fundo sem áudio salvo na biblioteca: {dest_file}")
        except Exception as copy_err:
            logger.error(f"Erro ao salvar fundo do YouTube na biblioteca: {copy_err}")

        yt_preset_statuses[status_key] = {
            "status": "done",
            "progress": 100,
            "title": title,
            "filename": dest_filename,
            "error": None
        }
    except Exception as e:
        logger.error(f"Erro no download de fundo do YouTube em background: {e}")
        yt_preset_statuses[status_key] = {
            "status": "error",
            "progress": 0,
            "title": "",
            "filename": "",
            "error": str(e)
        }


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

    threading.Thread(target=run_youtube_download_bg, args=(url, dict(current_user)), daemon=True).start()
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

    threading.Thread(target=run_bg_youtube_download_bg, args=(url, dict(current_user)), daemon=True).start()
    return {"status": "started"}


LRCLIB_API_URL = "https://lrclib.net/api"
LRCLIB_USER_AGENT = "Sal0-Karaoke/5.3.0 (+https://github.com/Sal0-Apps/Sal0-Karaoke)"
LYRICS_OVH_API_URL = "https://api.lyrics.ovh/v1"
LYRICS_PROVIDER_TIMEOUT = (3.05, 6)
MUSIXMATCH_API_URL = "https://apic-desktop.musixmatch.com/ws/1.1"
MUSIXMATCH_APP_ID = "web-desktop-app-v1.0"

class LyricsModel(BaseModel):
    lyrics_text: str = ""


class LyricsSearchRequest(BaseModel):
    query: str


class LyricsFetchRequest(BaseModel):
    id: int | None = None
    provider: str = "LRCLIB"
    artist_name: str = ""
    track_name: str = ""


def _lrclib_get(path: str, params: dict = None):
    """Consulta a LRCLIB apenas quando o usuário solicita uma busca de letra."""
    try:
        response = requests.get(
            f"{LRCLIB_API_URL}{path}",
            params=params,
            headers={
                "Accept": "application/json",
                "User-Agent": LRCLIB_USER_AGENT
            },
            timeout=LYRICS_PROVIDER_TIMEOUT
        )
        if response.status_code == 429:
            raise HTTPException(
                status_code=429,
                detail="O serviço de letras está temporariamente com muitas consultas. Tente novamente em alguns instantes."
            )
        response.raise_for_status()
        return response.json()
    except HTTPException:
        raise
    except requests.Timeout:
        raise HTTPException(status_code=504, detail="A busca de letras demorou demais para responder.")
    except (requests.RequestException, ValueError):
        logger.warning("Falha ao consultar o serviço de letras LRCLIB.")
        raise HTTPException(status_code=502, detail="Não foi possível consultar o serviço de letras agora.")


def _plain_lyrics_from_lrclib(record: dict) -> str:
    """Prefere letra simples e remove timestamps LRC apenas quando necessário."""
    plain_lyrics = str(record.get("plainLyrics") or "").strip()
    if plain_lyrics:
        return plain_lyrics

    synced_lyrics = str(record.get("syncedLyrics") or "").strip()
    if not synced_lyrics:
        return ""

    lines = []
    for line in synced_lyrics.splitlines():
        text = re.sub(r"^\s*(?:\[[^\]]+\]\s*)+", "", line).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _lyrics_provider_get(url: str, params: dict = None, provider: str = "lyrics"):
    """Fetch JSON from a public lyrics provider without blocking local processing."""
    try:
        response = requests.get(
            url,
            params=params,
            headers={
                "Accept": "application/json",
                "User-Agent": LRCLIB_USER_AGENT
            },
            timeout=LYRICS_PROVIDER_TIMEOUT
        )
        if response.status_code == 429:
            logger.info("Lyrics provider %s is rate limited.", provider)
            return None
        response.raise_for_status()
        return response.json()
    except requests.Timeout:
        logger.info("Lyrics provider %s timed out.", provider)
    except (requests.RequestException, ValueError):
        logger.info("Lyrics provider %s is unavailable.", provider)
    return None


def _lyrics_ovh_query_parts(query: str) -> tuple[str, str] | None:
    """Extract artist and title from the common 'artist - title' format."""
    parts = re.split(r"\s+[\-–—|]\s+", (query or "").strip(), maxsplit=1)
    if len(parts) != 2:
        return None
    artist, title = (part.strip() for part in parts)
    return (artist, title) if artist and title else None


def _search_lrclib(query: str) -> list[dict]:
    payload = _lyrics_provider_get(
        f"{LRCLIB_API_URL}/search",
        params={"q": query},
        provider="LRCLIB"
    )
    if not isinstance(payload, list):
        return []

    results = []
    for item in payload[:10]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            continue
        lyrics_text = _plain_lyrics_from_lrclib(item)
        results.append({
            "provider": "LRCLIB",
            "id": item["id"],
            "track_name": item.get("trackName") or "Faixa sem título",
            "artist_name": item.get("artistName") or "Artista desconhecido",
            "album_name": item.get("albumName") or "",
            "duration": item.get("duration"),
            "instrumental": bool(item.get("instrumental")),
            "has_lyrics": bool(lyrics_text),
            "lyrics_text": lyrics_text
        })
    return results


def _fetch_lyrics_ovh(artist: str, title: str) -> str:
    if not artist or not title:
        return ""
    payload = _lyrics_provider_get(
        f"{LYRICS_OVH_API_URL}/{quote(artist, safe='')}/{quote(title, safe='')}",
        provider="Lyrics.ovh"
    )
    return str(payload.get("lyrics") or "").strip() if isinstance(payload, dict) else ""


def _musixmatch_token() -> str:
    """Get a short-lived Musixmatch desktop token without storing credentials."""
    payload = _lyrics_provider_get(
        f"{MUSIXMATCH_API_URL}/token.get",
        params={"app_id": MUSIXMATCH_APP_ID},
        provider="Musixmatch token"
    )
    if not isinstance(payload, dict):
        return ""
    return str(
        payload.get("message", {})
        .get("body", {})
        .get("user_token") or ""
    ).strip()


def _musixmatch_record(artist: str, title: str) -> dict | None:
    token = _musixmatch_token()
    if not token or not title:
        return None

    params = {
        "format": "json",
        "namespace": "lyrics_richsynched",
        "subtitle_format": "mxm",
        "app_id": MUSIXMATCH_APP_ID,
        "usertoken": token,
        "q_track": title,
    }
    if artist:
        params["q_artist"] = artist

    payload = _lyrics_provider_get(
        f"{MUSIXMATCH_API_URL}/macro.subtitles.get",
        params=params,
        provider="Musixmatch"
    )
    if not isinstance(payload, dict):
        return None

    body = payload.get("message", {}).get("body", {})
    macro_calls = body.get("macro_calls", {}) if isinstance(body, dict) else {}
    track_message = macro_calls.get("matcher.track.get", {}).get("message", {})
    track = track_message.get("body", {}).get("track", {})
    if not isinstance(track, dict):
        track = {}
    if track.get("instrumental") == 1:
        return None

    subtitle_message = macro_calls.get("track.subtitles.get", {}).get("message", {})
    subtitle_body = subtitle_message.get("body", {})
    subtitle_list = subtitle_body.get("subtitle_list", []) if isinstance(subtitle_body, dict) else []
    lyrics_text = ""
    if subtitle_list:
        subtitle = subtitle_list[0].get("subtitle", {})
        raw_subtitles = subtitle.get("subtitle_body", "") if isinstance(subtitle, dict) else ""
        try:
            subtitle_lines = json.loads(raw_subtitles)
        except (TypeError, ValueError):
            subtitle_lines = []
        if isinstance(subtitle_lines, list):
            lyrics_text = "\n".join(
                str(line.get("text") or "").strip()
                for line in subtitle_lines
                if isinstance(line, dict) and str(line.get("text") or "").strip()
            ).strip()

    if not lyrics_text:
        lyrics_message = macro_calls.get("track.lyrics.get", {}).get("message", {})
        lyrics_body = lyrics_message.get("body", {})
        lyrics = lyrics_body.get("lyrics", {}) if isinstance(lyrics_body, dict) else {}
        lyrics_text = str(lyrics.get("lyrics_body") or "").strip() if isinstance(lyrics, dict) else ""

    if not lyrics_text:
        return None
    return {
        "track_name": track.get("track_name") or title,
        "artist_name": track.get("artist_name") or artist or "Artista desconhecido",
        "lyrics_text": lyrics_text
    }


def _search_musixmatch(query: str) -> list[dict]:
    parts = _lyrics_ovh_query_parts(query)
    artist, title = parts if parts else ("", query.strip())
    record = _musixmatch_record(artist, title)
    if not record:
        return []
    return [{
        "provider": "Musixmatch",
        "id": None,
        "track_name": record["track_name"],
        "artist_name": record["artist_name"],
        "album_name": "",
        "duration": None,
        "instrumental": False,
        "has_lyrics": True,
        "lyrics_text": record["lyrics_text"]
    }]


def _fetch_lyrics_musixmatch(artist: str, title: str) -> str:
    record = _musixmatch_record(artist, title)
    return str(record.get("lyrics_text") or "").strip() if record else ""


def _search_lyrics_ovh(query: str) -> list[dict]:
    parts = _lyrics_ovh_query_parts(query)
    if not parts:
        return []
    artist, title = parts
    lyrics_text = _fetch_lyrics_ovh(artist, title)
    if not lyrics_text:
        return []
    return [{
        "provider": "Lyrics.ovh",
        "id": None,
        "track_name": title,
        "artist_name": artist,
        "album_name": "",
        "duration": None,
        "instrumental": False,
        "has_lyrics": True,
        "lyrics_text": lyrics_text
    }]


def search_lyrics_providers(query: str) -> list[dict]:
    """Query free providers in parallel, following SyncLyrics' resilient strategy."""
    providers = (_search_lrclib, _search_lyrics_ovh, _search_musixmatch)
    results = []
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = [executor.submit(provider, query) for provider in providers]
        for future in as_completed(futures):
            try:
                results.extend(future.result())
            except Exception as exc:
                logger.info("Lyrics provider failed: %s", type(exc).__name__)
    return results


def find_lyrics_automatically(query: str) -> tuple[str, dict | None]:
    """Busca a melhor letra disponível sem tornar a internet obrigatória ao pipeline."""
    query = (query or "").strip()
    if len(query) < 2:
        return "", None

    payload = search_lyrics_providers(query)

    query_normalized = re.sub(r"\s+", " ", query.lower()).strip()
    best_match = None
    best_score = -1.0
    for item in payload:
        if not isinstance(item, dict) or item.get("instrumental") or not item.get("has_lyrics"):
            continue
        lyrics_text = str(item.get("lyrics_text") or "").strip()
        if not lyrics_text:
            continue

        candidate_name = " ".join([
            str(item.get("track_name") or ""),
            str(item.get("artist_name") or "")
        ]).lower()
        score = difflib.SequenceMatcher(None, query_normalized, candidate_name).ratio()
        if score > best_score:
            best_match = (lyrics_text, item)
            best_score = score

    if not best_match:
        logger.info("Nenhuma letra online encontrada para a música selecionada.")
        return "", None

    lyrics_text, record = best_match
    return lyrics_text, {
        "track_name": record.get("track_name") or "Faixa sem título",
        "artist_name": record.get("artist_name") or "Artista desconhecido"
    }


@app.post("/api/lyrics/search")
def search_lyrics_online(data: LyricsSearchRequest, current_user: dict = Depends(get_current_user)):
    """Pesquisa provedores públicos e devolve apenas metadados para escolha do usuário."""
    query = data.query.strip()
    if not 2 <= len(query) <= 160:
        raise HTTPException(status_code=400, detail="Informe entre 2 e 160 caracteres para buscar a letra.")

    provider_results = search_lyrics_providers(query)
    results = [
        {key: value for key, value in item.items() if key != "lyrics_text"}
        for item in provider_results
    ]
    return {
        "provider": "LRCLIB + Lyrics.ovh + Musixmatch",
        "results": results,
        "online_unavailable": not results,
        "message": "Nenhuma fonte online respondeu. Você ainda pode colar a letra manualmente." if not results else ""
    }


@app.post("/api/lyrics/fetch")
def fetch_lyrics_online(data: LyricsFetchRequest, current_user: dict = Depends(get_current_user)):
    """Obtém a letra da faixa escolhida e deixa a revisão final para a interface local."""
    provider = (data.provider or "LRCLIB").strip().lower()
    if provider == "lyrics.ovh":
        track_name = data.track_name.strip()
        artist_name = data.artist_name.strip()
        if not track_name or not artist_name:
            raise HTTPException(status_code=400, detail="Artista e faixa são necessários para importar esta letra.")
        lyrics_text = _fetch_lyrics_ovh(artist_name, track_name)
        if not lyrics_text:
            raise HTTPException(status_code=404, detail="Essa faixa não possui uma letra disponível para importar.")
        return {
            "provider": "Lyrics.ovh",
            "track_name": track_name,
            "artist_name": artist_name,
            "lyrics_text": lyrics_text
        }

    if provider == "musixmatch":
        track_name = data.track_name.strip()
        artist_name = data.artist_name.strip()
        if not track_name:
            raise HTTPException(status_code=400, detail="O título da faixa é necessário para importar esta letra.")
        lyrics_text = _fetch_lyrics_musixmatch(artist_name, track_name)
        if not lyrics_text:
            raise HTTPException(status_code=404, detail="Essa faixa não possui uma letra disponível para importar.")
        return {
            "provider": "Musixmatch",
            "track_name": track_name,
            "artist_name": artist_name or "Artista desconhecido",
            "lyrics_text": lyrics_text
        }

    if provider != "lrclib" or not data.id or data.id <= 0:
        raise HTTPException(status_code=400, detail="Identificador de letra inválido.")

    payload = _lrclib_get(f"/get/{data.id}")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="O serviço de letras retornou uma resposta inválida.")

    lyrics_text = _plain_lyrics_from_lrclib(payload)
    if not lyrics_text:
        raise HTTPException(status_code=404, detail="Essa faixa não possui uma letra disponível para importar.")

    return {
        "provider": "LRCLIB",
        "track_name": payload.get("trackName") or "Faixa sem título",
        "artist_name": payload.get("artistName") or "Artista desconhecido",
        "lyrics_text": lyrics_text
    }

@app.get("/api/lyrics")
def get_saved_lyrics(current_user: dict = Depends(get_current_user)):
    """Retorna a letra salva no servidor."""
    lyrics_file = config_path(current_user, "saved_lyrics.txt")
    if os.path.exists(lyrics_file):
        try:
            with open(lyrics_file, "r", encoding="utf-8") as f:
                return {"lyrics_text": f.read()}
        except Exception as e:
            logger.error(f"Erro ao ler letra do servidor: {e}")
    return {"lyrics_text": ""}

@app.post("/api/lyrics")
def save_lyrics_server(data: LyricsModel, current_user: dict = Depends(get_current_user)):
    """Salva a letra da música no servidor."""
    try:
        lyrics_file = config_path(current_user, "saved_lyrics.txt")
        os.makedirs(os.path.dirname(lyrics_file), exist_ok=True)
        with open(lyrics_file, "w", encoding="utf-8") as f:
            f.write(data.lyrics_text or "")
        return {"status": "saved"}
    except Exception as e:
        logger.error(f"Erro ao salvar letra no servidor: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao salvar letra no servidor: {e}")

@app.delete("/api/lyrics")
def delete_lyrics_server(current_user: dict = Depends(get_current_user)):
    """Exclui a letra salva do servidor."""
    try:
        lyrics_file = config_path(current_user, "saved_lyrics.txt")
        if os.path.exists(lyrics_file):
            os.remove(lyrics_file)
        return {"status": "deleted"}
    except Exception as e:
        logger.error(f"Erro ao excluir letra do servidor: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao excluir letra do servidor: {e}")



# Sistema de Logs de Diagnóstico v5.3.0
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
    """Monta um relatório atual no momento do clique, limitado ao administrador."""
    require_admin(current_user)

    def read_tail(path: str, limit: int = 1024 * 1024) -> str:
        if not os.path.exists(path):
            return "(arquivo ainda não criado)"
        try:
            with open(path, "rb") as file:
                file.seek(0, os.SEEK_END)
                size = file.tell()
                file.seek(max(0, size - limit))
                return file.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return f"(não foi possível ler: {type(exc).__name__})"

    with state_lock:
        current_state = dict(state)
    report = "\n".join([
        "Sal0 Karaokê v5.3.0 — diagnóstico ao vivo",
        f"Gerado em: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "=== ESTADO ATUAL ===",
        json.dumps(current_state, ensure_ascii=False, indent=2),
        "",
        "=== LOG DA APLICAÇÃO (TRECHO MAIS RECENTE) ===",
        read_tail(RUNTIME_LOG_FILE),
        "",
        "=== LOG DE DIAGNÓSTICO (TRECHO MAIS RECENTE) ===",
        read_tail(DIAGNOSTIC_LOG_FILE),
    ])
    return Response(
        content=report,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sal0_karaoke_logs_atuais.txt"}
    )


class ProfileModel(BaseModel):
    name: str
    whisper_model: str = "large-v3-turbo"
    font_size: int = 32
    text_color: str = "#00FFFF"
    text_position: str = "bottom"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    subtitle_mode: str = "syllable"
    words_per_line: int = 0
    max_chars_line: int = 0
    break_on_punctuation: bool = True
    background_mode: str = "original"
    show_instrumental: bool = True
    transcribe_source: str = "vocals"
    show_next_line_preview: bool = False
    keep_first_line_visible: bool = False
    enable_correction: bool = False
    enable_vad: bool = False
    transcription_preset: str = "karaoke"
    save_to_library: bool = True
    only_remove_vocals: bool = False

BUILTIN_PROFILES = {
    "Karaokê equilibrado": {
        "description": "O ponto de partida recomendado: acompanha a voz sem cortar canto suave ou refrões longos.",
        "_builtin": True,
        "whisper_model": "large-v3-turbo",
        "font_size": 32,
        "text_color": "#00FFFF",
        "text_position": "bottom",
        "subtitle_mode": "syllable",
        "words_per_line": 0,
        "max_chars_line": 38,
        "break_on_punctuation": True,
        "background_mode": "original",
        "show_instrumental": True,
        "transcribe_source": "vocals",
        "show_next_line_preview": False,
        "keep_first_line_visible": False,
        "enable_correction": False,
        "enable_vad": False,
        "transcription_preset": "karaoke",
        "save_to_library": True,
        "only_remove_vocals": False,
    },
    "Canto contínuo": {
        "description": "Dá mais espaço a notas sustentadas, vozes suaves e músicas com poucas pausas.",
        "_builtin": True,
        "whisper_model": "large-v3-turbo",
        "font_size": 32,
        "text_color": "#00FFFF",
        "text_position": "bottom",
        "subtitle_mode": "syllable",
        "words_per_line": 0,
        "max_chars_line": 36,
        "break_on_punctuation": True,
        "background_mode": "original",
        "show_instrumental": True,
        "transcribe_source": "vocals",
        "show_next_line_preview": True,
        "keep_first_line_visible": False,
        "enable_correction": False,
        "enable_vad": False,
        "transcription_preset": "continuous",
        "save_to_library": True,
        "only_remove_vocals": False,
    },
    "Voz difícil ou mix": {
        "description": "Mais paciente para vocais abafados, separação imperfeita, rap rápido ou dueto.",
        "_builtin": True,
        "whisper_model": "large-v3",
        "font_size": 32,
        "text_color": "#00FFFF",
        "text_position": "bottom",
        "subtitle_mode": "word",
        "words_per_line": 6,
        "max_chars_line": 38,
        "break_on_punctuation": True,
        "background_mode": "original",
        "show_instrumental": True,
        "transcribe_source": "original",
        "show_next_line_preview": True,
        "keep_first_line_visible": False,
        "enable_correction": True,
        "enable_vad": False,
        "transcription_preset": "difficult",
        "save_to_library": True,
        "only_remove_vocals": False,
    },
    "Criação rápida": {
        "description": "Uma prévia mais leve para testar visual e letra antes da versão final.",
        "_builtin": True,
        "whisper_model": "small",
        "font_size": 32,
        "text_color": "#00FFFF",
        "text_position": "bottom",
        "subtitle_mode": "word",
        "words_per_line": 6,
        "max_chars_line": 38,
        "break_on_punctuation": True,
        "background_mode": "original",
        "show_instrumental": True,
        "transcribe_source": "vocals",
        "show_next_line_preview": False,
        "keep_first_line_visible": False,
        "enable_correction": False,
        "enable_vad": True,
        "transcription_preset": "fast",
        "save_to_library": True,
        "only_remove_vocals": False,
    },
}

PROFILE_DEFAULT_FIELDS = {
    "subtitle_mode": "syllable",
    "words_per_line": 0,
    "max_chars_line": 40,
    "break_on_punctuation": True,
    "background_mode": "original",
    "show_instrumental": True,
    "transcribe_source": "vocals",
    "show_next_line_preview": False,
    "keep_first_line_visible": False,
    "enable_correction": False,
    "enable_vad": False,
    "transcription_preset": "karaoke",
    "save_to_library": True,
    "only_remove_vocals": False,
    "description": "Perfil personalizado por você.",
    "_builtin": False,
}

def load_profiles(user: dict) -> dict:
    """Carrega perfis pessoais e inclui opções prontas sem sobrescrevê-los."""
    profiles_file = config_path(user, "profiles.json")
    profiles = {}
    try:
        if os.path.exists(profiles_file):
            with open(profiles_file, "r", encoding="utf-8") as f:
                profiles = json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar arquivo de perfis: {e}")

    changed = False
    for name, builtin in BUILTIN_PROFILES.items():
        if name not in profiles:
            profiles[name] = dict(builtin)
            changed = True

    for name, profile_data in profiles.items():
        if name in BUILTIN_PROFILES:
            # Perfis prontos acompanham as melhorias do aplicativo.
            if profile_data != BUILTIN_PROFILES[name]:
                profiles[name] = dict(BUILTIN_PROFILES[name])
                changed = True
            continue
        if "enable_correction" not in profile_data:
            profile_data["enable_correction"] = profile_data.get("pause_for_editing", False)
            changed = True
        for field, default_value in PROFILE_DEFAULT_FIELDS.items():
            if field not in profile_data:
                profile_data[field] = default_value
                changed = True

    if changed or not os.path.exists(profiles_file):
        try:
            os.makedirs(os.path.dirname(profiles_file), exist_ok=True)
            with open(profiles_file, "w", encoding="utf-8") as f:
                json.dump(profiles, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erro ao atualizar arquivo de perfis: {e}")
    return profiles

@app.get("/api/profiles")
def get_profiles(current_user: dict = Depends(get_current_user)):
    """Retorna todos os perfis salvos."""
    return load_profiles(current_user)

@app.post("/api/profiles")
def save_profile(profile: ProfileModel, current_user: dict = Depends(get_current_user)):
    """Salva ou atualiza um perfil de uso."""
    profiles = load_profiles(current_user)
    profile_name = profile.name.strip()
    if not profile_name:
        raise HTTPException(status_code=400, detail="Informe um nome para o perfil.")
    if profile_name in BUILTIN_PROFILES:
        raise HTTPException(status_code=400, detail="Perfis prontos não podem ser sobrescritos. Salve sua variação com outro nome.")
    profiles[profile_name] = {
        "description": "Perfil personalizado por você.",
        "_builtin": False,
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
        "keep_first_line_visible": profile.keep_first_line_visible,
        "enable_correction": profile.enable_correction,
        "enable_vad": profile.enable_vad,
        "transcription_preset": profile.transcription_preset,
        "save_to_library": profile.save_to_library,
        "only_remove_vocals": profile.only_remove_vocals
    }
    try:
        with open(config_path(current_user, "profiles.json"), "w", encoding="utf-8") as f:
            import json
            json.dump(profiles, f, indent=4, ensure_ascii=False)
        return {"status": "success", "profiles": profiles}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar perfil em disco: {e}")

@app.delete("/api/profiles/{name}")
def delete_profile(name: str, current_user: dict = Depends(get_current_user)):
    """Remove um perfil de uso."""
    if name == "Padrão" or name in BUILTIN_PROFILES:
        raise HTTPException(status_code=400, detail="Perfis prontos do aplicativo não podem ser excluídos.")
    profiles = load_profiles(current_user)
    if name in profiles:
        del profiles[name]
        try:
            with open(config_path(current_user, "profiles.json"), "w", encoding="utf-8") as f:
                import json
                json.dump(profiles, f, indent=4, ensure_ascii=False)
            return {"status": "success", "profiles": profiles}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao salvar arquivo após exclusão: {e}")
    raise HTTPException(status_code=404, detail="Perfil de uso não encontrado.")

@app.get("/api/last_profile")
def get_last_profile(current_user: dict = Depends(get_current_user)):
    """Retorna o nome do último perfil utilizado."""
    last_profile_file = config_path(current_user, "last_profile.json")
    if os.path.exists(last_profile_file):
        try:
            with open(last_profile_file, "r", encoding="utf-8") as f:
                import json
                return json.load(f)
        except Exception:
            pass
    return {"last_profile": "Karaokê equilibrado"}

@app.post("/api/last_profile")
def save_last_profile(data: dict, current_user: dict = Depends(get_current_user)):
    """Salva o nome do último perfil utilizado."""
    try:
        last_profile_file = config_path(current_user, "last_profile.json")
        os.makedirs(os.path.dirname(last_profile_file), exist_ok=True)
        with open(last_profile_file, "w", encoding="utf-8") as f:
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
    username = session.get("username")
    user_record = users.get(username)
    if not user_record:
        sessions.pop(x_session_token, None)
        save_sessions(sessions)
        return {"status": "login"}
    if session.get("created_at") and (time.time() - session["created_at"]) > (30 * 24 * 3600):
        sessions.pop(x_session_token, None)
        save_sessions(sessions)
        return {"status": "login"}
    return {
        "status": "authenticated",
        "username": username,
        "role": user_record.get("role", "user")
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
    validate_new_credentials(username, password)

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
    validate_new_credentials(username, password)
    if role not in {"user", "admin"}:
        raise HTTPException(status_code=400, detail="Função de usuário inválida.")

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
        sessions = load_sessions()
        sessions = {token: session for token, session in sessions.items() if session.get("username") != username}
        save_sessions(sessions)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Usuário não encontrado.")

# --- SISTEMA DE BIBLIOTECA & HISTÓRICO ---

@app.get("/api/library")
def get_library_files(current_user: dict = Depends(get_current_user)):
    """Retorna as listas de arquivos disponíveis na biblioteca (videos, photos, history)."""
    result = {"videos": [], "photos": [], "history": []}
    library_dir = get_user_paths(current_user)["library"]
    for section in ["videos", "photos", "history"]:
        path = os.path.join(library_dir, section)
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

    target_dir = os.path.join(get_user_paths(current_user)["library"], section)
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

    paths = get_user_paths(current_user)
    final_mp4 = os.path.join(paths["output"], "final_karaoke.mp4")
    if not os.path.exists(final_mp4):
        raise HTTPException(status_code=400, detail="Nenhum vídeo finalizado encontrado para salvar no histórico.")

    dest_dir = os.path.join(paths["library"], "history")
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, safe_title)

    try:
        shutil.copy2(final_mp4, dest_path)
        logger.info(f"Vídeo de karaokê salvo no histórico: {safe_title}")
        return {"status": "success", "filename": safe_title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar vídeo no histórico: {e}")

class RenameRequest(BaseModel):
    old_name: str
    new_name: str

@app.put("/api/library/{section}/rename")
def rename_library_file(
    section: str,
    req: RenameRequest,
    current_user: dict = Depends(get_current_user)
):
    """Renomeia um arquivo na biblioteca (videos, photos ou history)."""
    library_dir = get_user_paths(current_user)["library"]
    valid_sections = {
        "videos": os.path.join(library_dir, "videos"),
        "photos": os.path.join(library_dir, "photos"),
        "history": os.path.join(library_dir, "history")
    }
    if section not in valid_sections:
        raise HTTPException(status_code=400, detail="Seção de biblioteca inválida.")

    target_dir = valid_sections[section]
    old_file = os.path.basename(req.old_name)
    new_file = os.path.basename(req.new_name)

    # Manter a extensão original se a nova string não especificar extensão
    old_ext = os.path.splitext(old_file)[1]
    if not os.path.splitext(new_file)[1]:
        new_file += old_ext

    safe_name = "".join([c for c in new_file if c.isalnum() or c in ' ._-']).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")

    src_path = os.path.join(target_dir, old_file)
    dst_path = os.path.join(target_dir, safe_name)

    if not os.path.exists(src_path):
        raise HTTPException(status_code=404, detail=f"Arquivo '{old_file}' não encontrado.")

    if os.path.exists(dst_path) and old_file != safe_name:
        raise HTTPException(status_code=400, detail=f"Já existe um arquivo com o nome '{safe_name}'.")

    try:
        os.rename(src_path, dst_path)
        logger.info(f"Arquivo renomeado de '{old_file}' para '{safe_name}' na seção '{section}'")
        return {"status": "success", "new_name": safe_name}
    except Exception as e:
        logger.error(f"Erro ao renomear arquivo: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao renomear arquivo: {e}")


@app.delete("/api/library/{section}/{filename}")
def delete_from_library(section: str, filename: str, current_user: dict = Depends(get_current_user)):
    """Exclui fisicamente um arquivo da biblioteca."""
    if section not in ["videos", "photos", "history"]:
        raise HTTPException(status_code=400, detail="Seção inválida.")

    safe_filename = os.path.basename(filename)
    file_path = os.path.join(get_user_paths(current_user)["library"], section, safe_filename)

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
    file_path = os.path.join(get_user_paths(current_user)["library"], section, safe_filename)

    if os.path.exists(file_path):
        return FileResponse(file_path, filename=safe_filename)

    raise HTTPException(status_code=404, detail="Arquivo não encontrado na biblioteca.")


def iter_file_range(file_path: str, start: int, end: int, chunk_size: int = 1024 * 1024):
    """Entrega somente o trecho solicitado para permitir seek em áudio e vídeo."""
    with open(file_path, "rb") as media_file:
        media_file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = media_file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def inline_file_response(file_path: str, media_type: str, request: Request):
    """Responde a Range requests usadas pelos players HTML para avançar e voltar."""
    file_size = os.path.getsize(file_path)
    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": "inline"
    }
    range_header = request.headers.get("range", "").strip()

    if not range_header:
        return FileResponse(file_path, media_type=media_type, headers=common_headers)

    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
    if not match:
        return Response(
            status_code=416,
            headers={**common_headers, "Content-Range": f"bytes */{file_size}"}
        )

    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return Response(
            status_code=416,
            headers={**common_headers, "Content-Range": f"bytes */{file_size}"}
        )

    if start_text:
        start = int(start_text)
        end = min(int(end_text), file_size - 1) if end_text else file_size - 1
    else:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            return Response(
                status_code=416,
                headers={**common_headers, "Content-Range": f"bytes */{file_size}"}
            )
        start = max(file_size - suffix_length, 0)
        end = file_size - 1

    if start >= file_size or end < start:
        return Response(
            status_code=416,
            headers={**common_headers, "Content-Range": f"bytes */{file_size}"}
        )

    content_length = end - start + 1
    headers = {
        **common_headers,
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(content_length)
    }
    return StreamingResponse(
        iter_file_range(file_path, start, end),
        status_code=206,
        media_type=media_type,
        headers=headers
    )


@app.get("/api/library/preview/{section}/{filename}")
def preview_from_library(
    section: str,
    filename: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Abre áudio/vídeo na interface sem forçar download."""
    if section not in ["videos", "photos", "history"]:
        raise HTTPException(status_code=400, detail="Seção inválida.")
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(get_user_paths(current_user)["library"], section, safe_filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado na biblioteca.")
    media_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    return inline_file_response(file_path, media_type, request)


PUBLIC_DOWNLOADS_FILE = "/data/output/public_downloads.json"
public_downloads_lock = threading.Lock()


def create_public_download(owner: dict, history_filename: str) -> str | None:
    if not history_filename:
        return None
    file_path = os.path.abspath(os.path.join(get_user_paths(owner)["library"], "history", os.path.basename(history_filename)))
    if not os.path.isfile(file_path):
        return None
    download_token = uuid.uuid4().hex + uuid.uuid4().hex
    with public_downloads_lock:
        records = {}
        if os.path.exists(PUBLIC_DOWNLOADS_FILE):
            try:
                with open(PUBLIC_DOWNLOADS_FILE, "r", encoding="utf-8") as file:
                    records = json.load(file)
            except Exception:
                records = {}
        records[download_token] = {
            "owner_username": owner.get("username"),
            "file_path": file_path,
            "filename": os.path.basename(history_filename),
            "created_at": time.time()
        }
        os.makedirs(os.path.dirname(PUBLIC_DOWNLOADS_FILE), exist_ok=True)
        with open(PUBLIC_DOWNLOADS_FILE, "w", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
    return download_token


@app.get("/api/public/download/{download_token}")
def public_download(download_token: str):
    """Download direto por link aleatório enviado ao Telegram, sem expor sessão ou caminho."""
    if not re.fullmatch(r"[a-f0-9]{64}", download_token or ""):
        raise HTTPException(status_code=404, detail="Link inválido.")
    with public_downloads_lock:
        try:
            with open(PUBLIC_DOWNLOADS_FILE, "r", encoding="utf-8") as file:
                record = json.load(file).get(download_token)
        except Exception:
            record = None
    if not record:
        raise HTTPException(status_code=404, detail="Link não encontrado.")
    file_path = os.path.abspath(str(record.get("file_path") or ""))
    allowed_root = os.path.abspath("/data") + os.sep
    if not file_path.startswith(allowed_root) or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Vídeo removido ou indisponível.")
    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=os.path.basename(record.get("filename") or "sal0_karaoke.mp4")
    )

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
    cache_dir = get_user_paths(current_user)["cache"]
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
    cache_dir = get_user_paths(current_user)["cache"]
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
    require_task_control(current_user)
    global correction_event
    correction_event.set()
    return {"status": "success", "message": "Renderização retomada sem alterações."}


@app.get("/api/segments_to_edit")
def get_segments_to_edit(current_user: dict = Depends(get_current_user)):
    require_task_control(current_user)
    global segments_to_edit
    return segments_to_edit

@app.post("/api/continue_process")
def continue_process(data: ContinueProcessModel, current_user: dict = Depends(get_current_user)):
    require_task_control(current_user)
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
    require_task_control(current_user)
    logger.info("Solicitação de cancelamento recebida de %s.", current_user.get("username"))

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

    # O worker libera o lock no bloco finally, depois de realmente encerrar.
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
        snapshot = dict(state)
    owner = snapshot.get("owner_username")
    owns_task = owner == current_user.get("username")
    active = snapshot.get("status") in {"processing", "downloading", "waiting_for_user_correction", "awaiting_review"}
    if owner and not owns_task and not is_admin(current_user):
        if active:
            return {
                "status": "busy",
                "step": "Servidor ocupado por outra criação",
                "progress": 0,
                "owned_by_current_user": False,
                "can_cancel": False
            }
        return {"status": "idle", "owned_by_current_user": False, "can_cancel": False}
    snapshot["owned_by_current_user"] = owns_task
    snapshot["can_cancel"] = bool(active and (owns_task or is_admin(current_user)))
    snapshot["result_available_to_current_user"] = owns_task
    if not is_admin(current_user):
        snapshot.pop("owner_username", None)
        snapshot.pop("owner_role", None)
        snapshot.pop("result_file", None)
        snapshot.pop("public_download_token", None)
    return snapshot

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
    max_chars_line: int = Form(0),
    break_on_punctuation: bool = Form(True),
    enable_vad: bool = Form(False),
    transcription_preset: str = Form("karaoke"),
    background_mode: str = Form("image"),
    show_instrumental: bool = Form(True),
    transcribe_source: str = Form("vocals"),
    show_next_line_preview: bool = Form(False),
    lyrics_text: str = Form(None),
    lyrics_mode: str = Form("auto"),
    enable_correction: bool = Form(False),
    keep_first_line_visible: bool = Form(False),
    pause_for_editing: bool = Form(False),
    youtube_url: str = Form(None),
    library_audio: str = Form(None),
    library_bg: str = Form(None),
    save_to_library: bool = Form(False),
    only_remove_vocals: bool = Form(False),
    app_base_url: str = Form(""),
    easy_mode: bool = Form(False)
):
    """
    Recebe os arquivos enviados, valida a concorrência e inicia o pipeline em segundo plano.
    """
    if easy_mode:
        easy_config = load_easy_mode_config()
        if not easy_config.get("enabled", True):
            raise HTTPException(status_code=403, detail="O Modo Facil foi desativado pelo administrador.")
        whisper_model = easy_config["whisper_model"]
        font_size = easy_config["font_size"]
        text_color = "#00FFFF"
        text_position = "bottom"
        subtitle_mode = "syllable"
        words_per_line = 0
        max_chars_line = 0
        break_on_punctuation = True
        enable_vad = False
        transcription_preset = easy_config["transcription_preset"]
        background_mode = "image" if (bg_file or library_bg) else "original"
        show_instrumental = easy_config["show_instrumental"]
        transcribe_source = easy_config["transcribe_source"]
        show_next_line_preview = easy_config["show_next_line_preview"]
        lyrics_text = None
        lyrics_mode = "auto"
        enable_correction = False
        keep_first_line_visible = False
        pause_for_editing = False
        save_to_library = True
        only_remove_vocals = False

    if transcription_preset not in {"karaoke", "continuous", "difficult", "fast"}:
        raise HTTPException(status_code=400, detail="Perfil de leitura da voz inválido.")

    # 1. Verificar se o servidor já está processando alguma música
    if processing_lock.locked():
        with state_lock:
            if state.get("status") in ["idle", "error", "done"]:
                try:
                    processing_lock.release()
                    logger.info("Failsafe: lock de concorrência obsoleto liberado com sucesso.")
                except Exception:
                    pass
            else:
                raise HTTPException(
                    status_code=429,
                    detail="O servidor está ocupado processando outro vídeo. Por favor, aguarde alguns minutos."
                )

    user_paths = get_user_paths(current_user)
    cache_dir = user_paths["cache"]
    library_dir = user_paths["library"]
    os.makedirs(cache_dir, exist_ok=True)
    cache_meta_file = os.path.join(cache_dir, "cache_meta.json")

    lyrics_mode = (lyrics_mode or "auto").strip().lower()
    if lyrics_mode not in {"auto", "manual"}:
        raise HTTPException(status_code=400, detail="Modo de letra inválido.")
    if lyrics_mode == "auto":
        # A letra automática pertence à mídia atual. Nunca reutilizar o texto
        # enviado pelo navegador, que pode ter vindo da música anterior.
        lyrics_text = ""

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
                shutil.copy2(input_bg_path, os.path.join(library_dir, "photos", bg_filename))
        elif library_bg:
            src_bg = os.path.join(library_dir, "photos", library_bg)
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
                    lib_video_dir = os.path.join(library_dir, "videos")
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
        lib_video_dir = os.path.join(library_dir, "videos")
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
                shutil.copy2(input_bg_path, os.path.join(library_dir, "photos", bg_filename))
        elif library_bg:
            src_bg = os.path.join(library_dir, "photos", library_bg)
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
            shutil.copy2(input_audio_path, os.path.join(library_dir, "videos", audio_file.filename))

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
                shutil.copy2(input_bg_path, os.path.join(library_dir, "photos", bg_filename))
        elif library_bg:
            src_bg = os.path.join(library_dir, "photos", library_bg)
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
                shutil.copy2(input_bg_path, os.path.join(library_dir, "photos", bg_filename))
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
            shutil.copy2(os.path.join(library_dir, "photos", library_bg), input_bg_path)
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

    update_state(
        "processing",
        "Uploading",
        5,
        original_filename=orig_name,
        owner_username=current_user.get("username"),
        owner_role=current_user.get("role")
    )

    background_tasks.add_task(
        run_pipeline,
        input_audio_path=input_audio_path,
        input_bg_path=input_bg_path,
        whisper_model=whisper_model,
        font_size=font_size,
        text_color=text_color,
        text_position=text_position,
        subtitle_mode=subtitle_mode,
        words_per_line=words_per_line,
        max_chars_line=max_chars_line,
        break_on_punctuation=break_on_punctuation,
        enable_vad=enable_vad,
        transcription_preset=transcription_preset,
        background_mode=background_mode,
        show_instrumental=show_instrumental,
        transcribe_source=transcribe_source,
        show_next_line_preview=show_next_line_preview,
        lyrics_text=lyrics_text,
        lyrics_mode=lyrics_mode,
        enable_correction=enable_correction,
        keep_first_line_visible=keep_first_line_visible,
        youtube_url=youtube_url,
        only_remove_vocals=only_remove_vocals,
        owner_user=dict(current_user),
        cache_dir=cache_dir,
        output_dir=user_paths["output"],
        library_dir=library_dir,
        app_base_url=(app_base_url or "").strip()
    )

    return {"status": "processing"}

def send_telegram_video_flow(
    token: str,
    chat_id: str,
    video_path: str,
    orig_name: str,
    history_filename: str,
    public_download_token: str,
    base_url: str = "",
    external_url: str = ""
):
    """Envia o vídeo e links diretos sem reutilizar a sessão web do usuário."""
    if not token or not chat_id:
        return

    limit_50mb = 50 * 1024 * 1024

    def build_download_links() -> str:
        if not public_download_token:
            return ""
        route = f"/api/public/download/{public_download_token}"
        links = []
        if base_url.strip():
            links.append(f'🏠 <a href="{base_url.rstrip("/")}{route}">Baixar na rede local</a>')
        if external_url.strip():
            links.append(f'🌐 <a href="{external_url.rstrip("/")}{route}">Baixar pelo acesso externo</a>')
        return "\n" + "\n".join(links) if links else ""

    try:
        file_size = os.path.getsize(video_path)
        download_block = build_download_links()
        if file_size > limit_50mb:
            file_size_mb = file_size / (1024 * 1024)
            send_telegram_notification(
                token,
                chat_id,
                f"🎬 <b>Sal0 Karaokê</b>: <b>{orig_name}</b> ficou pronto!\n\n"
                f"O arquivo tem <b>{file_size_mb:.1f} MB</b> e está na Biblioteca como <b>{history_filename}</b>."
                f"{download_block}"
            )
            return

        success = False
        with open(video_path, "rb") as video_file:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendVideo",
                data={
                    "chat_id": chat_id,
                    "caption": f"🎥 <b>Sal0 Karaokê</b>: aqui está <b>{orig_name}</b>!",
                    "parse_mode": "HTML"
                },
                files={"video": video_file},
                timeout=90
            )
            success = response.status_code == 200
            if not success:
                logger.error("Telegram recusou o vídeo com HTTP %s.", response.status_code)

        status_text = "Vídeo enviado e salvo na sua Biblioteca." if success else "O envio do arquivo falhou, mas ele está salvo na sua Biblioteca."
        send_telegram_notification(
            token,
            chat_id,
            f"✅ <b>Sal0 Karaokê</b>: <b>{orig_name}</b> concluído. {status_text}{download_block}"
        )
    except Exception as exc:
        logger.error("Erro no envio em segundo plano para o Telegram: %s", exc)


def send_video_to_targets(
    targets: list[dict],
    video_path: str,
    orig_name: str,
    history_filename: str,
    public_download_token: str,
    base_url: str,
    external_url: str
):
    for target in targets:
        threading.Thread(
            target=send_telegram_video_flow,
            kwargs={
                "token": target["telegram_token"],
                "chat_id": target["telegram_chat_id"],
                "video_path": video_path,
                "orig_name": orig_name,
                "history_filename": history_filename,
                "public_download_token": public_download_token,
                "base_url": base_url,
                "external_url": external_url
            },
            daemon=True
        ).start()

def run_pipeline(
    input_audio_path: str,
    input_bg_path: str = None,
    whisper_model: str = "large-v3-turbo",
    font_size: int = 32,
    text_color: str = "#00FFFF",
    text_position: str = "bottom",
    subtitle_mode: str = "syllable",
    words_per_line: int = 0,
    max_chars_line: int = 0,
    break_on_punctuation: bool = True,
    enable_vad: bool = False,
    transcription_preset: str = "karaoke",
    background_mode: str = "original",
    show_instrumental: bool = True,
    transcribe_source: str = "vocals",
    show_next_line_preview: bool = False,
    lyrics_text: str = None,
    lyrics_mode: str = "auto",
    enable_correction: bool = False,
    keep_first_line_visible: bool = False,
    youtube_url: str = None,
    only_remove_vocals: bool = False,
    owner_user: dict = None,
    cache_dir: str = None,
    output_dir: str = None,
    library_dir: str = None,
    app_base_url: str = ""
):
    """Pipeline principal de processamento sequencial."""
    # Obter o lock de processamento exclusivo (segurança de job único)
    if not processing_lock.acquire(blocking=False):
        logger.warning("Bloqueio de concorrência ativado: Processamento já em andamento.")
        return

    owner_user = owner_user or {"username": state.get("owner_username"), "role": state.get("owner_role", "user")}
    owner_paths = get_user_paths(owner_user)
    cache_dir = cache_dir or owner_paths["cache"]
    output_dir = output_dir or owner_paths["output"]
    library_dir = library_dir or owner_paths["library"]
    saved_lyrics_file = os.path.join(output_dir, "saved_lyrics.txt")
    telegram_targets = get_notification_targets(owner_user)

    # Carregar URL externa configurada pelo usuário (para links de download no Telegram)
    ext_url_cfg = load_external_url_config()
    telegram_external_url = ext_url_cfg.get("external_url", "")
    telegram_base_url = app_base_url.strip()

    with state_lock:
        orig_name = state.get("original_filename", "final")

    try:
        import process_manager as pm
        pm.cancel_event.clear()
        pm.clear_active_process()

        # Notificação Telegram: Apenas início resumido
        notify_targets(telegram_targets, f"🎙️ <b>Sal0 Karaokê</b>: Iniciando processamento de <b>{orig_name}</b>...")

        # Pasta de saída mapeada via volume docker-compose
        os.makedirs(output_dir, exist_ok=True)

        final_mp4_path = os.path.join(output_dir, "final_karaoke.mp4")
        final_ass_path = os.path.join(output_dir, "karaoke.ass")

        # Limpar outputs anteriores se existirem
        if os.path.exists(final_mp4_path):
            os.remove(final_mp4_path)
        if os.path.exists(final_ass_path):
            os.remove(final_ass_path)

        # Configurar diretório de cache persistente
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
                notify_targets(telegram_targets, "🌐 <b>Sal0 Karaokê</b>: Iniciando download do YouTube...")

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

                    notify_targets(telegram_targets, f"📥 <b>Sal0 Karaokê</b>: Download concluído! <b>{orig_name}</b>")
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

        # Busca automática de letra: sempre usa a identidade da mídia atual.
        # O texto anterior é descartado para nunca orientar outra música.
        lyrics_text = (lyrics_text or "").strip() if lyrics_mode == "manual" else ""
        if lyrics_mode == "auto":
            cached_meta["lyrics_text"] = ""
            try:
                with open(cache_meta_file, "w", encoding="utf-8") as f:
                    json.dump(cached_meta, f, indent=4)
                if os.path.exists(saved_lyrics_file):
                    os.remove(saved_lyrics_file)
            except Exception as clear_error:
                logger.warning("Não foi possível limpar a letra automática anterior: %s", clear_error)

            update_state("processing", "Searching lyrics online", 10, original_filename=orig_name)
            auto_lyrics, auto_match = find_lyrics_automatically(orig_name)
            if auto_lyrics:
                lyrics_text = auto_lyrics
                cached_meta["lyrics_text"] = auto_lyrics
                try:
                    with open(cache_meta_file, "w", encoding="utf-8") as f:
                        json.dump(cached_meta, f, indent=4)
                    with open(saved_lyrics_file, "w", encoding="utf-8") as f:
                        f.write(auto_lyrics)
                    logger.info(
                        "Letra guia encontrada automaticamente: %s — %s",
                        auto_match["track_name"],
                        auto_match["artist_name"]
                    )
                except Exception as save_error:
                    logger.warning("A letra automática foi encontrada, mas não pôde ser salva: %s", save_error)
            else:
                logger.info("Seguindo sem letra guia automática para '%s'.", orig_name)

        # Invalidação Inteligente de Cache: comparar o hash/tamanho do arquivo de entrada atual com o cache
        new_audio_hash = None
        try:
            if os.path.exists(input_audio_path):
                new_audio_hash = f"{os.path.basename(input_audio_path)}_{os.path.getsize(input_audio_path)}"
        except Exception:
            pass

        cached_audio_hash = cached_meta.get("audio_hash")
        if (new_audio_hash and cached_audio_hash != new_audio_hash) or youtube_url:
            logger.info(f"Nova mídia detectada para processamento ({orig_name}). Limpando cache de áudio anterior...")
            for inter_file in ["original_converted.wav", "vocals.wav", "instrumental.wav", "transcribed_segments.json"]:
                inter_path = os.path.join(cache_dir, inter_file)
                if os.path.exists(inter_path):
                    try:
                        os.remove(inter_path)
                    except Exception:
                        pass
            cached_meta["audio_hash"] = new_audio_hash
            cached_meta["original_filename"] = orig_name
            with open(cache_meta_file, "w", encoding="utf-8") as cm_f:
                import json
                json.dump(cached_meta, cm_f, indent=4)
        else:
            logger.info(f"Reaproveitando cache de áudio válido para '{orig_name}' (audio_hash={new_audio_hash}).")

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
                notify_targets(telegram_targets, "🎵 <b>Sal0 Karaokê</b>: Extraindo áudio (15%)")
                extract_audio(input_audio_path, converted_wav)

            pm.check_cancelled()

            # Passo 2: Separar vocais e instrumental via Demucs
            vocals_wav = os.path.join(cache_dir, "vocals.wav")
            instrumental_wav = os.path.join(cache_dir, "instrumental.wav")

            if os.path.exists(vocals_wav) and os.path.exists(instrumental_wav):
                logger.info("Aproveitando áudio separado pelo Demucs do cache.")
                update_state(
                    "processing",
                    "Vocais separados (cache)",
                    55,
                    stage_progress=100,
                    stage_detail="Separação já disponível no cache"
                )
            else:
                pm.check_cancelled()
                update_state(
                    "processing",
                    "Separando vocais do áudio",
                    20,
                    stage_progress=0,
                    stage_detail="Preparando 4 análises locais"
                )
                notify_targets(telegram_targets, "✂️ <b>Sal0 Karaokê</b>: Iniciando a separação local de vocais")
                with tempfile.TemporaryDirectory() as demucs_tmp:
                    v_tmp, i_tmp = separate_vocals(converted_wav, demucs_tmp, update_callback=update_state)
                    shutil.move(v_tmp, vocals_wav)
                    shutil.move(i_tmp, instrumental_wav)

            pm.check_cancelled()

            # Se only_remove_vocals estiver ativo, pulamos transcrição e legenda, indo direto para renderização
            if only_remove_vocals:
                pm.check_cancelled()
                update_state("processing", "Rendering final video", 95)
                notify_targets(telegram_targets, "🎬 <b>Sal0 Karaokê</b>: Renderizando vídeo sem a voz do cantor (95%)")

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
                history_filename = save_video_to_history(final_mp4_path, orig_name, library_dir)
                public_token = create_public_download(owner_user, history_filename)
                save_result_metadata(output_dir, orig_name, history_filename)
                update_state("processing", "Cleaning temporary files", 98)
                update_state(
                    "done",
                    "Done",
                    100,
                    result_file=final_mp4_path,
                    history_filename=history_filename,
                    public_download_token=public_token
                )
                logger.info("Pipeline concluído: Vocais removidos do vídeo original com sucesso.")

                processing_lock.release()

                send_video_to_targets(
                    telegram_targets,
                    final_mp4_path,
                    orig_name,
                    history_filename,
                    public_token,
                    telegram_base_url,
                    telegram_external_url
                )
                return

            # Passo 3: Transcrever vocais com Whisper selecionado
            segments = None
            segments_cache_file = os.path.join(cache_dir, "transcribed_segments.json")
            lyrics_hint_hash = hashlib.sha256((lyrics_text or "").strip().encode("utf-8")).hexdigest()

            if (os.path.exists(segments_cache_file) and
                cached_meta.get("transcribe_source") == transcribe_source and
                cached_meta.get("whisper_model") == whisper_model and
                cached_meta.get("enable_vad") == enable_vad and
                cached_meta.get("transcription_preset") == transcription_preset and
                cached_meta.get("lyrics_hint_hash") == lyrics_hint_hash):
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
                notify_targets(telegram_targets, f"✍️ <b>Sal0 Karaokê</b>: Transcrevendo voz ({whisper_model}) (70%)")

                transcribe_audio = vocals_wav if transcribe_source == "vocals" else converted_wav
                logger.info(f"Fonte de transcrição escolhida: {transcribe_audio} (Modo: {transcribe_source})")

                # Verificar status do modelo Whisper com is_model_downloaded() para exibir a mensagem correta na UI
                if is_model_downloaded(whisper_model):
                    update_state("processing", f"Carregando Modelo Whisper {whisper_model} do disco e transcrevendo voz...", 65)
                else:
                    update_state("processing", f"Baixando Modelo de IA Whisper {whisper_model} no servidor...", 65)

                quality_preset = "max_quality" if whisper_model == "large-v3" else "standard"
                segments = transcribe_vocals(
                    transcribe_audio,
                    model_size=whisper_model,
                    initial_prompt=lyrics_text,
                    quality_mode=quality_preset,
                    enable_vad=enable_vad,
                    transcription_preset=transcription_preset,
                )

                if segments:
                    with open(segments_cache_file, "w", encoding="utf-8") as f:
                        import json
                        json.dump(segments, f, indent=4)
                    cached_meta["transcribe_source"] = transcribe_source
                    cached_meta["whisper_model"] = whisper_model
                    cached_meta["enable_vad"] = enable_vad
                    cached_meta["transcription_preset"] = transcription_preset
                    cached_meta["lyrics_hint_hash"] = lyrics_hint_hash
                    with open(cache_meta_file, "w", encoding="utf-8") as f:
                        import json
                        json.dump(cached_meta, f, indent=4)

            pm.check_cancelled()

            if not segments:
                raise ValueError("Nenhum vocal detectado ou transcrição vazia.")

            # A letra corrige apenas a grafia; os tempos continuam vindo do áudio.
            if lyrics_text and lyrics_text.strip():
                logger.info("Aplicando letra guia de forma conservadora, sem criar timestamps...")
                segments = align_lyrics(lyrics_text, segments)

            pm.check_cancelled()

            # --- NOVO: Passo de Pausa e Correção de Legendas (se ativado pelo usuário) ---
            if enable_correction:
                global segments_to_edit, correction_event
                segments_to_edit = segments
                correction_event.clear()

                update_state("waiting_for_user_correction", "Correction", 75)

                # Notificação Telegram para o usuário entrar no app e editar
                notify_targets(
                    telegram_targets,
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
            notify_targets(telegram_targets, "📝 <b>Sal0 Karaokê</b>: Gerando legenda (80%)")
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
            notify_targets(telegram_targets, "🎬 <b>Sal0 Karaokê</b>: Renderizando vídeo (95%)")
            bg_mode_param = "original_video" if (background_mode in ["original", "original_video"]) else background_mode
            render_karaoke_video(
                instrumental_path=instrumental_wav,
                ass_path=ass_path,
                output_mp4_path=final_mp4_path,
                background_image_path=input_bg_path,
                original_video_path=input_audio_path,
                background_mode=bg_mode_param
            )

            pm.check_cancelled()

            # Salvar opcionalmente a legenda ASS final gerada junto com o MP4
            shutil.copy(ass_path, final_ass_path)

            # Salvar automaticamente no histórico privado do dono da tarefa.
            history_filename = save_video_to_history(final_mp4_path, orig_name, library_dir)
            public_token = create_public_download(owner_user, history_filename)
            save_result_metadata(output_dir, orig_name, history_filename)

            # Passo 6: Limpar arquivos temporários (não removemos os uploads do cache)
            update_state("processing", "Cleaning temporary files", 98)
            logger.info("Preservando arquivos de entrada no cache para futuros reprocessamentos.")

            # Processamento local CONCLUÍDO na UI!
            update_state(
                "done",
                "Done",
                100,
                result_file=final_mp4_path,
                history_filename=history_filename,
                public_download_token=public_token
            )
            logger.info("Pipeline de Karaokê Maker concluído com sucesso!")

            # Liberar o lock de processamento imediatamente para que o usuário possa usar o site
            processing_lock.release()

            # Disparar envio do vídeo ao Telegram em segundo plano (thread separada)
            send_video_to_targets(
                telegram_targets,
                final_mp4_path,
                orig_name,
                history_filename,
                public_token,
                telegram_base_url,
                telegram_external_url
            )

    except Exception as e:
        logger.exception("Ocorreu um erro catastrófico durante o processamento do pipeline.")
        # Se foi cancelado cooperativamente, salvar estado correspondente
        if "Cancelado pelo usuário" in str(e):
            update_state("idle", "Idle", 0, error_message="Processamento cancelado pelo usuário.")
        else:
            update_state("error", "Error", 0, error_message=str(e))
            notify_targets(telegram_targets, f"❌ <b>Sal0 Karaokê</b>: Falha ao processar <b>{orig_name}</b>. Erro: {e}")

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
def download_file(
    request: Request,
    inline: bool = Query(False),
    current_user: dict = Depends(get_current_user)
):
    """Endpoint para baixar o arquivo final de vídeo karaokê."""
    output_dir = get_user_paths(current_user)["output"]
    file_path = os.path.join(output_dir, "final_karaoke.mp4")
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail="Arquivo de vídeo não encontrado. Por favor, processe um áudio primeiro."
        )
    orig_name = "final"
    meta_file = os.path.join(output_dir, "result_meta.json")
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as file:
                orig_name = json.load(file).get("original_filename", "final")
        except Exception:
            pass
    download_name = f"{orig_name}_karaokê.mp4"
    if inline:
        return inline_file_response(file_path, "video/mp4", request)
    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=download_name
    )
