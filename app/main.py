import socket
socket.setdefaulttimeout(120)  # Timeout de 120s para impedir travamentos de socket em downloads de IA
import os
import sys
import importlib
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
import random
import unicodedata
from urllib.parse import quote
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Header, Depends, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# Módulos do pipeline local
from audio_processor import extract_audio, extract_audio_mp3, get_file_duration, separate_vocals
from transcriber import transcribe_vocals
from subtitle_translator import (
    SUPPORTED_TARGET_LANGUAGES,
    cover_full_media_timeline,
    translate_subtitle_segments,
    write_srt,
)
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


YT_DLP_RUNTIME_DIR = "/data/output/yt_dlp_runtime"
YT_DLP_STAGING_DIR = "/data/output/yt_dlp_runtime_staging"
YT_DLP_BACKUP_DIR = "/data/output/yt_dlp_runtime_previous"
yt_dlp_operation_lock = threading.RLock()


class YtDlpLogAdapter:
    """Encaminha avisos úteis do yt-dlp ao log do servidor sem expor a interface a ruído interno."""

    def debug(self, message):
        if not str(message).startswith("[debug]"):
            logger.debug("yt-dlp: %s", message)

    def warning(self, message):
        logger.warning("yt-dlp: %s", message)

    def error(self, message):
        logger.error("yt-dlp: %s", message)


def load_yt_dlp(force_reload: bool = False):
    """Carrega primeiro a cópia persistente atualizada pelo administrador, quando disponível."""
    if os.path.isdir(YT_DLP_RUNTIME_DIR) and YT_DLP_RUNTIME_DIR not in sys.path:
        sys.path.insert(0, YT_DLP_RUNTIME_DIR)

    if force_reload:
        for module_name in tuple(sys.modules):
            if module_name == "yt_dlp" or module_name.startswith("yt_dlp."):
                sys.modules.pop(module_name, None)
        importlib.invalidate_caches()

    return importlib.import_module("yt_dlp")


def yt_dlp_version() -> str:
    load_yt_dlp()
    version_module = importlib.import_module("yt_dlp.version")
    return str(getattr(version_module, "__version__", "desconhecida"))


def youtube_download_options(outtmpl: str | None = None) -> dict:
    """Opções resilientes compartilhadas pelos downloads e pela leitura de metadados."""
    options = {
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "file_access_retries": 3,
        "concurrent_fragment_downloads": 4,
        "overwrites": True,
        "quiet": True,
        "no_warnings": True,
        "logger": YtDlpLogAdapter(),
    }
    if outtmpl:
        options["outtmpl"] = outtmpl
    return options


def find_downloaded_file(cache_dir: str, prefix: str) -> str:
    candidates = [
        os.path.join(cache_dir, filename)
        for filename in os.listdir(cache_dir)
        if filename.startswith(f"{prefix}.") and not filename.endswith((".part", ".ytdl"))
    ]
    candidates = [path for path in candidates if os.path.isfile(path) and os.path.getsize(path) > 0]
    if not candidates:
        raise RuntimeError("O YouTube não entregou um arquivo de mídia válido.")
    return max(candidates, key=os.path.getmtime)


def download_youtube(url: str, cache_dir: str) -> tuple[str, str]:
    """Baixa o melhor vídeo/áudio do YouTube usando yt-dlp com expurgo prévio e 'overwrites': True."""
    with yt_dlp_operation_lock:
        yt_dlp = load_yt_dlp()

        # Expurgo prévio obrigatório para impedir o reaproveitamento de download incompleto.
        for filename in os.listdir(cache_dir):
            if filename.startswith("original_input."):
                try:
                    os.remove(os.path.join(cache_dir, filename))
                except OSError:
                    pass

        base_options = youtube_download_options(os.path.join(cache_dir, "original_input.%(ext)s"))
        formats = (
            "bv*[height<=1080]+ba/b[height<=1080]/b",
            "b/bv*+ba",
        )
        title = "Vídeo do YouTube"
        last_error = None

        for attempt, media_format in enumerate(formats, start=1):
            options = {
                **base_options,
                "format": media_format,
                "merge_output_format": "mp4",
                "remux_video": "mp4",
            }
            try:
                logger.info("Download do YouTube: tentativa %s de %s.", attempt, len(formats))
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                title = str((info or {}).get("title") or title)
                return find_downloaded_file(cache_dir, "original_input"), title
            except Exception as exc:
                last_error = exc
                logger.warning("Tentativa %s do download do YouTube falhou: %s", attempt, exc)

        raise RuntimeError(f"Não foi possível baixar o vídeo do YouTube: {last_error}")

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
yt_dlp_update_lock = threading.Lock()
yt_dlp_update_state = {
    "status": "idle",
    "message": "Nenhuma atualização executada nesta sessão.",
    "error": None,
    "version": None,
}


def deno_runtime_version() -> str | None:
    executable = shutil.which("deno")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        first_line = (result.stdout or "").splitlines()[0].strip()
        return first_line or None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def run_yt_dlp_update():
    with yt_dlp_update_lock:
        yt_dlp_update_state.update({
            "status": "updating",
            "message": "Baixando a versão mais recente do mecanismo do YouTube...",
            "error": None,
        })

    try:
        if os.path.isdir(YT_DLP_STAGING_DIR):
            shutil.rmtree(YT_DLP_STAGING_DIR)
        os.makedirs(YT_DLP_STAGING_DIR, exist_ok=True)
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-cache-dir",
            "--upgrade",
            "--upgrade-strategy",
            "eager",
            "--pre",
            "--target",
            YT_DLP_STAGING_DIR,
            "yt-dlp[default]",
        ]
        with yt_dlp_operation_lock:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=900,
                check=False,
            )
            if result.returncode != 0:
                details = (result.stderr or result.stdout or "Falha não especificada.").strip()
                raise RuntimeError(details[-3000:])

            validation = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        f"sys.path.insert(0, {YT_DLP_STAGING_DIR!r}); "
                        "from yt_dlp.version import __version__; print(__version__)"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if validation.returncode != 0 or not (validation.stdout or "").strip():
                raise RuntimeError((validation.stderr or "O pacote baixado não pôde ser validado.")[-3000:])

            if os.path.isdir(YT_DLP_BACKUP_DIR):
                shutil.rmtree(YT_DLP_BACKUP_DIR)
            had_previous_runtime = os.path.isdir(YT_DLP_RUNTIME_DIR)
            if had_previous_runtime:
                os.replace(YT_DLP_RUNTIME_DIR, YT_DLP_BACKUP_DIR)
            os.replace(YT_DLP_STAGING_DIR, YT_DLP_RUNTIME_DIR)

            try:
                load_yt_dlp(force_reload=True)
                installed_version = yt_dlp_version()
            except Exception:
                if os.path.isdir(YT_DLP_RUNTIME_DIR):
                    shutil.rmtree(YT_DLP_RUNTIME_DIR)
                if had_previous_runtime and os.path.isdir(YT_DLP_BACKUP_DIR):
                    os.replace(YT_DLP_BACKUP_DIR, YT_DLP_RUNTIME_DIR)
                load_yt_dlp(force_reload=True)
                raise

            if os.path.isdir(YT_DLP_BACKUP_DIR):
                shutil.rmtree(YT_DLP_BACKUP_DIR)

        with yt_dlp_update_lock:
            yt_dlp_update_state.update({
                "status": "done",
                "message": "Mecanismo do YouTube atualizado e pronto para uso.",
                "error": None,
                "version": installed_version,
            })
        logger.info("yt-dlp atualizado em armazenamento persistente para %s.", installed_version)
    except Exception as exc:
        if os.path.isdir(YT_DLP_STAGING_DIR):
            shutil.rmtree(YT_DLP_STAGING_DIR, ignore_errors=True)
        logger.error("Falha ao atualizar yt-dlp: %s", exc)
        with yt_dlp_update_lock:
            yt_dlp_update_state.update({
                "status": "error",
                "message": "A atualização não foi concluída.",
                "error": str(exc),
            })


@app.get("/api/youtube-tools/status")
def get_youtube_tools_status(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    try:
        installed_version = yt_dlp_version()
    except Exception as exc:
        installed_version = None
        logger.warning("Não foi possível consultar a versão do yt-dlp: %s", exc)

    with yt_dlp_update_lock:
        update_snapshot = dict(yt_dlp_update_state)

    return {
        "yt_dlp_version": installed_version,
        "source": "persistent" if os.path.isfile(os.path.join(YT_DLP_RUNTIME_DIR, "yt_dlp", "__init__.py")) else "image",
        "deno_version": deno_runtime_version(),
        "update": update_snapshot,
    }


@app.post("/api/youtube-tools/update")
def update_youtube_tools(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    if processing_lock.locked():
        raise HTTPException(status_code=409, detail="Aguarde o processamento atual terminar antes de atualizar.")

    with yt_dlp_update_lock:
        if yt_dlp_update_state.get("status") == "updating":
            return {"status": "updating"}
        yt_dlp_update_state.update({
            "status": "updating",
            "message": "Preparando a atualização...",
            "error": None,
        })

    threading.Thread(target=run_yt_dlp_update, daemon=True).start()
    return {"status": "started"}

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
    "subtitle_filename": None,
    "original_subtitle_filename": None,
    "translated_subtitle_filename": None,
    "subtitle_language": None,
    "translation_error": "",
    "result_kind": None,
    "public_download_token": None,
    "process_summary": {}
}

PROCESSING_QUEUE_FILE = "/data/output/processing_queue.json"
PROCESSING_QUEUE_CONTROL_FILE = "/data/output/processing_queue_control.json"
PROCESSING_QUEUE_ROOT = "/data/output/queue_jobs"
processing_queue_lock = threading.Lock()
processing_queue_event = threading.Event()
processing_queue = []
processing_queue_paused = False
processing_queue_worker_started = False
ACTIVE_QUEUE_STATUSES = {"queued", "processing"}
legacy_cache_promotion_lock = threading.Lock()


class StagePauseRequested(Exception):
    def __init__(self, stage: str, label: str, progress: int):
        super().__init__(f"Pausado após a etapa: {label}")
        self.stage = stage
        self.label = label
        self.progress = progress


def load_stage_checkpoints(cache_dir: str | None) -> dict:
    if not cache_dir:
        return {"completed_stages": {}}
    checkpoint_file = os.path.join(cache_dir, "stage_checkpoints.json")
    try:
        with open(checkpoint_file, "r", encoding="utf-8") as saved_file:
            saved = json.load(saved_file)
        if isinstance(saved, dict) and isinstance(saved.get("completed_stages"), dict):
            return saved
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning("Não foi possível carregar os checkpoints da etapa: %s", exc)
    return {"completed_stages": {}}


def stage_checkpoint(cache_dir: str | None, stage: str) -> dict:
    return dict(load_stage_checkpoints(cache_dir).get("completed_stages", {}).get(stage) or {})


def persist_active_processing_seconds(cache_dir: str, elapsed_seconds: float) -> float:
    saved = load_stage_checkpoints(cache_dir)
    saved["active_processing_seconds"] = max(0.0, float(elapsed_seconds))
    checkpoint_file = os.path.join(cache_dir, "stage_checkpoints.json")
    temporary_file = f"{checkpoint_file}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as output_file:
        json.dump(saved, output_file, ensure_ascii=False, indent=2)
    os.replace(temporary_file, checkpoint_file)
    return saved["active_processing_seconds"]


def format_processing_duration(elapsed_seconds: float | int | None) -> str:
    total = max(0, round(float(elapsed_seconds or 0)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}min {seconds:02d}s"
    if minutes:
        return f"{minutes}min {seconds:02d}s"
    return f"{seconds}s"


def queue_pause_requested() -> bool:
    with processing_queue_lock:
        return processing_queue_paused


def save_stage_checkpoint(
    cache_dir: str,
    stage: str,
    label: str,
    progress: int,
    **details,
):
    os.makedirs(cache_dir, exist_ok=True)
    checkpoint_file = os.path.join(cache_dir, "stage_checkpoints.json")
    saved = load_stage_checkpoints(cache_dir)
    completed = saved.setdefault("completed_stages", {})
    completed[stage] = {
        "label": label,
        "progress": max(0, min(100, int(progress))),
        "saved_at": time.time(),
        **details,
    }
    saved["last_stage"] = stage
    saved["last_label"] = label
    temporary_file = f"{checkpoint_file}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as output_file:
        json.dump(saved, output_file, ensure_ascii=False, indent=2)
    os.replace(temporary_file, checkpoint_file)

    if queue_pause_requested():
        update_state(
            "paused",
            "Paused at stage checkpoint",
            progress,
            stage_progress=100,
            stage_detail=f"Checkpoint salvo após: {label}. É seguro reiniciar o servidor.",
        )
        raise StagePauseRequested(stage, label, progress)


def save_processing_queue_control_unlocked():
    os.makedirs(os.path.dirname(PROCESSING_QUEUE_CONTROL_FILE), exist_ok=True)
    with open(PROCESSING_QUEUE_CONTROL_FILE, "w", encoding="utf-8") as control_file:
        json.dump({"paused": processing_queue_paused}, control_file, ensure_ascii=False, indent=2)


def load_processing_queue_control():
    global processing_queue_paused
    processing_queue_paused = False
    if not os.path.isfile(PROCESSING_QUEUE_CONTROL_FILE):
        return
    try:
        with open(PROCESSING_QUEUE_CONTROL_FILE, "r", encoding="utf-8") as control_file:
            control = json.load(control_file)
        processing_queue_paused = bool(control.get("paused")) if isinstance(control, dict) else False
    except Exception as exc:
        logger.error("Não foi possível carregar o controle persistente da fila: %s", exc)


def save_processing_queue_unlocked():
    processing_queue[:] = [
        job for job in processing_queue
        if job.get("status") in ACTIVE_QUEUE_STATUSES
    ]
    os.makedirs(os.path.dirname(PROCESSING_QUEUE_FILE), exist_ok=True)
    with open(PROCESSING_QUEUE_FILE, "w", encoding="utf-8") as queue_file:
        json.dump(processing_queue, queue_file, ensure_ascii=False, indent=2)


def load_processing_queue():
    global processing_queue
    if not os.path.isfile(PROCESSING_QUEUE_FILE):
        processing_queue = []
        return
    try:
        with open(PROCESSING_QUEUE_FILE, "r", encoding="utf-8") as queue_file:
            loaded = json.load(queue_file)
        processing_queue = [
            job for job in (loaded if isinstance(loaded, list) else [])
            if isinstance(job, dict) and job.get("status") in ACTIVE_QUEUE_STATUSES
        ]
        for job in processing_queue:
            if job.get("status") == "processing":
                job["status"] = "queued"
                job["message"] = "Recuperado após reinício do servidor."
        save_processing_queue_unlocked()
    except Exception as exc:
        logger.error("Não foi possível carregar a fila persistente: %s", exc)
        processing_queue = []


def public_queue_job(job: dict, waiting_position: int | None = None) -> dict:
    result = {
        "id": job.get("id"),
        "title": job.get("title"),
        "owner_username": job.get("owner_username"),
        "owner_role": job.get("owner_role"),
        "status": job.get("status"),
        "message": job.get("message", ""),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "finished_at": job.get("finished_at"),
        "history_filename": job.get("history_filename"),
        "subtitle_filename": job.get("subtitle_filename"),
    }
    if waiting_position is not None:
        result["position"] = waiting_position
    return result


def enqueue_processing_job(job: dict) -> int:
    with processing_queue_lock:
        active_for_user = sum(
            1 for queued_job in processing_queue
            if queued_job.get("owner_username") == job.get("owner_username")
            and queued_job.get("status") in {"queued", "processing"}
        )
        if active_for_user >= 25:
            raise HTTPException(status_code=429, detail="Sua fila atingiu o limite de 25 vídeos pendentes.")
        processing_queue.append(job)
        position = sum(1 for queued_job in processing_queue if queued_job.get("status") == "queued")
        save_processing_queue_unlocked()
    processing_queue_event.set()
    return position


def ensure_processing_queue_capacity(username: str):
    with processing_queue_lock:
        active_for_user = sum(
            1 for queued_job in processing_queue
            if queued_job.get("owner_username") == username
            and queued_job.get("status") in {"queued", "processing"}
        )
    if active_for_user >= 25:
        raise HTTPException(status_code=429, detail="Sua fila atingiu o limite de 25 vídeos pendentes.")


def ensure_processing_queue_access(
    current_user: dict,
):
    """Durante um trabalho ativo, permite novos itens ao dono ou administrador."""
    with processing_queue_lock:
        active_job = next(
            (job for job in processing_queue if job.get("status") == "processing"),
            None,
        )
    if not active_job:
        return
    if not is_admin(current_user) and active_job.get("owner_username") != current_user.get("username"):
        raise HTTPException(
            status_code=409,
            detail="Aguarde: o servidor está processando um trabalho de outro perfil.",
        )


def active_queue_pipeline_for_user(current_user: dict) -> dict:
    """Retorna os parâmetros do trabalho ativo visível ao usuário, quando existir."""
    with processing_queue_lock:
        active_job = next(
            (
                job for job in processing_queue
                if job.get("status") == "processing"
                and (
                    is_admin(current_user)
                    or job.get("owner_username") == current_user.get("username")
                )
            ),
            None,
        )
    return dict((active_job or {}).get("pipeline") or {})


def queue_cache_dir_for_user(current_user: dict) -> str | None:
    pipeline = active_queue_pipeline_for_user(current_user)
    cache_dir = pipeline.get("cache_dir")
    return cache_dir if cache_dir and os.path.isdir(cache_dir) else None


def remove_finished_queue_cache(cache_dir: str | None):
    if not cache_dir:
        return
    queue_root = os.path.abspath(PROCESSING_QUEUE_ROOT)
    job_root = os.path.abspath(os.path.dirname(cache_dir))
    if os.path.commonpath([queue_root, job_root]) != queue_root or job_root == queue_root:
        logger.warning("Cache da fila fora da raiz permitida; limpeza ignorada: %s", job_root)
        return
    shutil.rmtree(job_root, ignore_errors=True)


def promote_queue_cache_in_background(job_cache: str, owner: dict):
    """Atualiza o cache reutilizável sem impedir que o worker inicie o próximo trabalho."""
    try:
        with legacy_cache_promotion_lock:
            if not job_cache or not os.path.isdir(job_cache):
                return
            legacy_cache = get_user_paths(owner)["cache"]
            os.makedirs(legacy_cache, exist_ok=True)
            for cached_name in os.listdir(legacy_cache):
                cached_path = os.path.join(legacy_cache, cached_name)
                try:
                    if os.path.isdir(cached_path):
                        shutil.rmtree(cached_path)
                    else:
                        os.remove(cached_path)
                except OSError as exc:
                    logger.warning("Não foi possível atualizar o cache reutilizável: %s", exc)
            shutil.copytree(job_cache, legacy_cache, dirs_exist_ok=True)
    except Exception:
        logger.exception("Não foi possível promover o cache concluído em segundo plano.")
    finally:
        remove_finished_queue_cache(job_cache)


def cleanup_queue_cache_in_background(job_cache: str | None):
    """Remove o cache isolado sem impedir que o próximo trabalho seja iniciado."""
    remove_finished_queue_cache(job_cache)


def processing_queue_worker():
    while True:
        processing_queue_event.wait(timeout=2)
        processing_queue_event.clear()

        while True:
            with processing_queue_lock:
                if processing_queue_paused:
                    break
                job = next((item for item in processing_queue if item.get("status") == "queued"), None)
                if not job:
                    break
                job["status"] = "processing"
                job["started_at"] = time.time()
                job["message"] = "Processando no servidor."
                save_processing_queue_unlocked()

            pipeline = dict(job.get("pipeline") or {})
            owner = dict(pipeline.get("owner_user") or {})
            summary = dict(job.get("process_summary") or {})
            deferred_cache_cleanup = False
            try:
                update_state(
                    "processing",
                    "Preparing queued job",
                    1,
                    original_filename=job.get("title") or "Vídeo",
                    owner_username=owner.get("username"),
                    owner_role=owner.get("role"),
                    process_summary=summary,
                )
                run_pipeline(**pipeline)
                with state_lock:
                    final_status = state.get("status")
                    final_error = state.get("error_message", "")
                    final_history_filename = state.get("history_filename")
                    final_subtitle_filename = state.get("subtitle_filename")
                if final_status == "done":
                    queue_status = "done"
                    queue_message = "Resultado concluído e salvo na Biblioteca."
                    job_cache = pipeline.get("cache_dir")
                    if job_cache and os.path.isdir(job_cache) and not pipeline.get("subtitle_only"):
                        deferred_cache_cleanup = True
                        threading.Thread(
                            target=promote_queue_cache_in_background,
                            args=(job_cache, owner),
                            daemon=True,
                            name=f"cache-promotion-{job.get('id', 'job')}",
                        ).start()
                elif final_status == "idle" and "cancel" in final_error.casefold():
                    queue_status = "cancelled"
                    queue_message = "Processamento cancelado."
                else:
                    queue_status = "error"
                    queue_message = final_error or "O processamento não foi concluído."
            except StagePauseRequested as exc:
                queue_status = "queued"
                queue_message = f"Pausado com segurança após: {exc.label}."
                deferred_cache_cleanup = True
                logger.info("Trabalho devolvido à fila no checkpoint %s.", exc.stage)
            except Exception as exc:
                logger.exception("Falha inesperada no trabalhador da fila.")
                queue_status = "error"
                queue_message = str(exc)

            with processing_queue_lock:
                job["status"] = queue_status
                job["message"] = queue_message
                if queue_status == "queued":
                    job.pop("started_at", None)
                    job.pop("finished_at", None)
                else:
                    job["finished_at"] = time.time()
                if queue_status == "done":
                    job["history_filename"] = final_history_filename
                    job["subtitle_filename"] = final_subtitle_filename
                save_processing_queue_unlocked()
            if not deferred_cache_cleanup:
                threading.Thread(
                    target=cleanup_queue_cache_in_background,
                    args=(pipeline.get("cache_dir"),),
                    daemon=True,
                    name=f"cache-cleanup-{job.get('id', 'job')}",
                ).start()
            processing_queue_event.set()


def start_processing_queue_worker():
    global processing_queue_worker_started
    if processing_queue_worker_started:
        return
    processing_queue_worker_started = True
    threading.Thread(target=processing_queue_worker, daemon=True, name="karaoke-processing-queue").start()
    processing_queue_event.set()


@app.get("/api/queue")
def get_processing_queue(current_user: dict = Depends(get_current_user)):
    with processing_queue_lock:
        waiting = 0
        visible = []
        for job in processing_queue:
            if job.get("status") not in ACTIVE_QUEUE_STATUSES:
                continue
            position = None
            if job.get("status") == "queued":
                waiting += 1
                position = waiting
            if is_admin(current_user) or job.get("owner_username") == current_user.get("username"):
                visible.append(public_queue_job(job, position))
        active_job = next((job for job in processing_queue if job.get("status") == "processing"), None)
        paused = processing_queue_paused
    return {
        "jobs": visible[-100:],
        "paused": paused,
        "pause_pending": bool(paused and active_job),
    }


@app.post("/api/queue/pause")
def pause_processing_queue(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    global processing_queue_paused
    with processing_queue_lock:
        processing_queue_paused = True
        active_job = next((job for job in processing_queue if job.get("status") == "processing"), None)
        save_processing_queue_control_unlocked()
    return {
        "status": "pause_pending" if active_job else "paused",
        "message": (
            "A etapa atual continuará até o checkpoint e então a fila será pausada com segurança."
            if active_job else
            "A fila está pausada e permanecerá assim após reiniciar o servidor."
        ),
    }


@app.post("/api/queue/resume")
def resume_processing_queue(current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    global processing_queue_paused
    with processing_queue_lock:
        processing_queue_paused = False
        save_processing_queue_control_unlocked()
    processing_queue_event.set()
    return {"status": "resumed", "message": "A fila foi retomada."}


@app.delete("/api/queue/{job_id}")
def remove_queued_job(job_id: str, current_user: dict = Depends(get_current_user)):
    cache_dir = None
    with processing_queue_lock:
        job = next((item for item in processing_queue if item.get("id") == job_id), None)
        if not job:
            raise HTTPException(status_code=404, detail="Item da fila não encontrado.")
        if not (is_admin(current_user) or job.get("owner_username") == current_user.get("username")):
            raise HTTPException(status_code=403, detail="Este item pertence a outro usuário.")
        if job.get("status") != "queued":
            raise HTTPException(status_code=409, detail="Somente itens que ainda aguardam podem ser removidos.")
        cache_dir = (job.get("pipeline") or {}).get("cache_dir")
        processing_queue.remove(job)
        save_processing_queue_unlocked()
    threading.Thread(
        target=cleanup_queue_cache_in_background,
        args=(cache_dir,),
        daemon=True,
        name=f"queue-remove-{job_id}",
    ).start()
    processing_queue_event.set()
    return {"status": "cancelled"}


class QueueMoveRequest(BaseModel):
    direction: str


@app.patch("/api/queue/{job_id}/position")
def move_queued_job(
    job_id: str,
    payload: QueueMoveRequest,
    current_user: dict = Depends(get_current_user),
):
    direction = payload.direction.strip().lower()
    if direction not in {"up", "down"}:
        raise HTTPException(status_code=422, detail="Direção inválida para a fila.")

    with processing_queue_lock:
        job = next((item for item in processing_queue if item.get("id") == job_id), None)
        if not job:
            raise HTTPException(status_code=404, detail="Item da fila não encontrado.")
        if job.get("status") != "queued":
            raise HTTPException(status_code=409, detail="Somente itens aguardando podem mudar de posição.")
        if not (is_admin(current_user) or job.get("owner_username") == current_user.get("username")):
            raise HTTPException(status_code=403, detail="Este item pertence a outro usuário.")

        eligible_indexes = [
            index for index, queued_job in enumerate(processing_queue)
            if queued_job.get("status") == "queued"
            and (
                is_admin(current_user)
                or queued_job.get("owner_username") == current_user.get("username")
            )
        ]
        current_index = processing_queue.index(job)
        current_position = eligible_indexes.index(current_index)
        target_position = current_position + (-1 if direction == "up" else 1)
        if target_position < 0 or target_position >= len(eligible_indexes):
            raise HTTPException(status_code=409, detail="O item já está no limite permitido da fila.")
        target_index = eligible_indexes[target_position]
        processing_queue[current_index], processing_queue[target_index] = (
            processing_queue[target_index],
            processing_queue[current_index],
        )
        save_processing_queue_unlocked()

    processing_queue_event.set()
    return {"status": "moved", "direction": direction}

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
    subtitle_filename: str = None,
    original_subtitle_filename: str = None,
    translated_subtitle_filename: str = None,
    subtitle_language: str = None,
    translation_error: str = None,
    result_kind: str = None,
    public_download_token: str = None,
    stage_progress: int | None = None,
    stage_detail: str = "",
    process_summary: dict | None = None
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
            state["subtitle_filename"] = None
            state["original_subtitle_filename"] = None
            state["translated_subtitle_filename"] = None
            state["subtitle_language"] = None
            state["translation_error"] = ""
            state["result_kind"] = None
            state["public_download_token"] = None
        if owner_role is not None:
            state["owner_role"] = owner_role
        if history_filename is not None:
            state["history_filename"] = history_filename
        if subtitle_filename is not None:
            state["subtitle_filename"] = subtitle_filename
        if original_subtitle_filename is not None:
            state["original_subtitle_filename"] = original_subtitle_filename
        if translated_subtitle_filename is not None:
            state["translated_subtitle_filename"] = translated_subtitle_filename
        if subtitle_language is not None:
            state["subtitle_language"] = subtitle_language
        if translation_error is not None:
            state["translation_error"] = translation_error
        if result_kind is not None:
            state["result_kind"] = result_kind
        if public_download_token is not None:
            state["public_download_token"] = public_download_token
        if process_summary is not None:
            state["process_summary"] = dict(process_summary)

        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                import json
                json.dump(state, f, indent=4)
        except Exception as e:
            logger.error(f"Erro ao salvar estado no disco: {e}")


def update_process_summary(**changes):
    """Atualiza apenas o resumo curto exibido durante a produção."""
    with state_lock:
        summary = dict(state.get("process_summary") or {})
        summary.update({key: value for key, value in changes.items() if value is not None})
        state["process_summary"] = summary
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Erro ao salvar resumo do processamento: {e}")

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
    with processing_queue_lock:
        load_processing_queue_control()
        load_processing_queue()
    start_processing_queue_worker()


def karaoke_download_filename(original_name: str) -> str:
    """Monta um nome portátil preservando o título original da música."""
    raw_name = str(original_name or "").strip()
    root, extension = os.path.splitext(raw_name)
    if extension.lower() in {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".mp4", ".mkv", ".avi", ".mov", ".webm"}:
        raw_name = root
    safe_name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "", raw_name)
    safe_name = re.sub(r"\s+", " ", safe_name).strip(" ._-") or "Sal0 Karaokê"
    safe_name = safe_name[:180].rstrip(" ._-")
    if safe_name.casefold().endswith(" - karaokê") or safe_name.casefold().endswith(" - karaoke"):
        return f"{safe_name}.mp4"
    return f"{safe_name} - Karaokê.mp4"


def save_video_to_history(video_path: str, orig_name: str, library_dir: str) -> str:
    """Salva uma cópia permanente no histórico do dono da tarefa."""
    if not video_path or not os.path.exists(video_path):
        return None
    try:
        lib_history_dir = os.path.join(library_dir, "history")
        os.makedirs(lib_history_dir, exist_ok=True)
        dest_filename = karaoke_download_filename(orig_name)
        safe_name = os.path.splitext(dest_filename)[0]

        dest_path = os.path.join(lib_history_dir, dest_filename)
        counter = 1
        while os.path.exists(dest_path):
            dest_filename = f"{safe_name} ({counter}).mp4"
            dest_path = os.path.join(lib_history_dir, dest_filename)
            counter += 1

        shutil.copy2(video_path, dest_path)
        logger.info(f"Vídeo de karaokê '{orig_name}' salvo com sucesso no Histórico: {dest_path}")
        return dest_filename
    except Exception as err:
        logger.error(f"Erro ao salvar vídeo no histórico: {err}")
        return None


def save_srt_result(srt_path: str, orig_name: str, library_dir: str, language_label: str) -> str:
    """Salva um SRT como resultado independente, sem criar um vídeo associado."""
    if not srt_path or not os.path.isfile(srt_path):
        return None
    base_name = os.path.splitext(karaoke_download_filename(orig_name))[0]
    base_name = re.sub(r" - Karaok[eê]$", "", base_name, flags=re.IGNORECASE)
    safe_language = re.sub(r"[^a-zA-Z0-9_-]", "", language_label or "original") or "original"
    filename_root = f"{base_name} - Legenda {safe_language}"
    history_dir = os.path.join(library_dir, "history")
    os.makedirs(history_dir, exist_ok=True)
    filename = f"{filename_root}.srt"
    destination = os.path.join(history_dir, filename)
    counter = 1
    while os.path.exists(destination):
        filename = f"{filename_root} ({counter}).srt"
        destination = os.path.join(history_dir, filename)
        counter += 1
    shutil.copy2(srt_path, destination)
    return filename


def save_result_metadata(
    output_dir: str,
    original_filename: str,
    history_filename: str,
    subtitle_filename: str = None,
    subtitle_language: str = None,
    original_subtitle_filename: str = None,
    translated_subtitle_filename: str = None,
    translation_error: str = "",
    result_kind: str = None,
):
    try:
        with open(os.path.join(output_dir, "result_meta.json"), "w", encoding="utf-8") as file:
            json.dump({
                "original_filename": original_filename,
                "history_filename": history_filename,
                "subtitle_filename": subtitle_filename,
                "subtitle_language": subtitle_language,
                "original_subtitle_filename": original_subtitle_filename,
                "translated_subtitle_filename": translated_subtitle_filename,
                "translation_error": translation_error,
                "result_kind": result_kind,
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
        response = requests.post(url, json=payload, timeout=10)
        if not response.ok:
            logger.error("Telegram rejeitou a notificação: HTTP %s (%s)", response.status_code, response.text[:300])
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
    "config_version": 2,
    "enabled": True,
    "whisper_model": "large-v3-turbo",
    "font_size": 50,
    "text_color": "#008080",
    "text_position": "middle",
    "subtitle_mode": "syllable",
    "words_per_line": 0,
    "max_chars_line": 0,
    "break_on_punctuation": True,
    "enable_vad": False,
    "transcription_preset": "difficult",
    "background_mode": "random_library",
    "random_backgrounds": [],
    "random_background_owner": "",
    "transcribe_source": "vocals",
    "show_next_line_preview": True,
    "show_instrumental": True,
    "lyrics_mode": "auto",
    "enable_correction": False,
    "keep_first_line_visible": False,
    "save_to_library": True,
    "only_remove_vocals": False,
}


class EasyModeModel(BaseModel):
    config_version: int = 2
    enabled: bool = True
    whisper_model: str = "large-v3-turbo"
    font_size: int = 50
    text_color: str = "#008080"
    text_position: str = "middle"
    subtitle_mode: str = "syllable"
    words_per_line: int = 0
    max_chars_line: int = 0
    break_on_punctuation: bool = True
    enable_vad: bool = False
    transcription_preset: str = "difficult"
    background_mode: str = "random_library"
    random_backgrounds: list[str] = Field(default_factory=list)
    random_background_owner: str = ""
    transcribe_source: str = "vocals"
    show_next_line_preview: bool = True
    show_instrumental: bool = True
    lyrics_mode: str = "auto"
    enable_correction: bool = False
    keep_first_line_visible: bool = False
    save_to_library: bool = True
    only_remove_vocals: bool = False


def normalize_easy_mode_config(config: dict | None = None) -> dict:
    submitted = config or {}
    normalized = {
        key: submitted.get(key, default)
        for key, default in EASY_MODE_DEFAULTS.items()
    }
    normalized["config_version"] = EASY_MODE_DEFAULTS["config_version"]
    if normalized["whisper_model"] not in {"large-v3-turbo", "large-v3", "medium", "small", "tiny"}:
        normalized["whisper_model"] = EASY_MODE_DEFAULTS["whisper_model"]
    if normalized["transcription_preset"] not in {"karaoke", "continuous", "difficult", "fast"}:
        normalized["transcription_preset"] = EASY_MODE_DEFAULTS["transcription_preset"]
    if normalized["transcribe_source"] not in {"original", "vocals"}:
        normalized["transcribe_source"] = EASY_MODE_DEFAULTS["transcribe_source"]
    if normalized["text_position"] not in {"bottom", "middle", "top"}:
        normalized["text_position"] = EASY_MODE_DEFAULTS["text_position"]
    if normalized["subtitle_mode"] not in {"syllable", "word", "line", "phrase"}:
        normalized["subtitle_mode"] = EASY_MODE_DEFAULTS["subtitle_mode"]
    if normalized["background_mode"] not in {"original", "image", "color", "random_library"}:
        normalized["background_mode"] = EASY_MODE_DEFAULTS["background_mode"]
    if normalized["lyrics_mode"] not in {"auto", "manual"}:
        normalized["lyrics_mode"] = EASY_MODE_DEFAULTS["lyrics_mode"]
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(normalized.get("text_color", ""))):
        normalized["text_color"] = EASY_MODE_DEFAULTS["text_color"]
    normalized["font_size"] = max(24, min(72, int(normalized.get("font_size", 50))))
    normalized["words_per_line"] = max(0, min(30, int(normalized.get("words_per_line", 0))))
    normalized["max_chars_line"] = max(0, min(100, int(normalized.get("max_chars_line", 0))))
    random_backgrounds = normalized.get("random_backgrounds", [])
    if not isinstance(random_backgrounds, list):
        random_backgrounds = []
    clean_backgrounds = []
    for filename in random_backgrounds:
        safe_name = os.path.basename(str(filename).strip().replace("\\", "/"))
        if safe_name and not safe_name.startswith(".") and safe_name not in clean_backgrounds:
            clean_backgrounds.append(safe_name)
        if len(clean_backgrounds) >= 100:
            break
    normalized["random_backgrounds"] = clean_backgrounds
    normalized["random_background_owner"] = str(normalized.get("random_background_owner", "")).strip()[:100]
    for bool_key in (
        "enabled", "break_on_punctuation", "enable_vad", "show_next_line_preview",
        "show_instrumental", "enable_correction", "keep_first_line_visible",
        "save_to_library", "only_remove_vocals",
    ):
        normalized[bool_key] = bool(normalized.get(bool_key, EASY_MODE_DEFAULTS[bool_key]))
    return normalized


def load_easy_mode_config() -> dict:
    if not os.path.exists(EASY_MODE_FILE):
        return normalize_easy_mode_config()
    try:
        with open(EASY_MODE_FILE, "r", encoding="utf-8") as file:
            saved_config = json.load(file)
        if int(saved_config.get("config_version", 0) or 0) < EASY_MODE_DEFAULTS["config_version"]:
            # A configuração já aprovada pelo administrador é preservada. Somente
            # o novo padrão de fundo passa a usar a coleção aleatória.
            saved_config["config_version"] = EASY_MODE_DEFAULTS["config_version"]
            saved_config["background_mode"] = "random_library"
            saved_config.setdefault("random_backgrounds", [])
            saved_config.setdefault("random_background_owner", "")
        return normalize_easy_mode_config(saved_config)
    except Exception as exc:
        logger.warning("Não foi possível carregar o Modo Rápido: %s", exc)
        return normalize_easy_mode_config()


@app.get("/api/easy-mode")
def get_easy_mode_config(current_user: dict = Depends(get_current_user)):
    config = load_easy_mode_config()
    if not is_admin(current_user):
        config.pop("random_backgrounds", None)
        config.pop("random_background_owner", None)
    return config


@app.post("/api/easy-mode")
def save_easy_mode_config(config: EasyModeModel, current_user: dict = Depends(get_current_user)):
    require_admin(current_user)
    normalized = normalize_easy_mode_config(config.dict())
    photos_dir = os.path.join(get_user_paths(current_user)["library"], "photos")
    normalized["random_backgrounds"] = [
        filename for filename in normalized["random_backgrounds"]
        if os.path.isfile(os.path.join(photos_dir, filename))
    ]
    normalized["random_background_owner"] = current_user.get("username", "")
    try:
        os.makedirs(os.path.dirname(EASY_MODE_FILE), exist_ok=True)
        with open(EASY_MODE_FILE, "w", encoding="utf-8") as file:
            json.dump(normalized, file, indent=4, ensure_ascii=False)
        return {"status": "success", "config": normalized}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar o Modo Rápido: {exc}")


QUICK_BACKGROUND_STAGE_PREFIX = ".quick_random_background"


def stage_quick_random_background(config: dict, current_user: dict) -> tuple[str | None, str | None]:
    """Copia um fundo global sorteado para uma área oculta da conta solicitante."""
    owner = user_from_username(config.get("random_background_owner", ""))
    if not owner or not is_admin(owner):
        return None, None

    owner_photos = os.path.join(get_user_paths(owner)["library"], "photos")
    candidates = [
        filename for filename in config.get("random_backgrounds", [])
        if os.path.isfile(os.path.join(owner_photos, filename))
    ]
    if not candidates:
        return None, None

    selected = random.choice(candidates)
    source_path = os.path.join(owner_photos, selected)
    target_dir = os.path.join(get_user_paths(current_user)["library"], "photos")
    extension = os.path.splitext(selected)[1].lower()
    staged_name = f"{QUICK_BACKGROUND_STAGE_PREFIX}{extension}"
    staged_path = os.path.join(target_dir, staged_name)
    try:
        for filename in os.listdir(target_dir):
            if filename.startswith(QUICK_BACKGROUND_STAGE_PREFIX):
                previous_path = os.path.join(target_dir, filename)
                if os.path.isfile(previous_path):
                    os.remove(previous_path)
        shutil.copy2(source_path, staged_path)
    except OSError as exc:
        logger.warning("Não foi possível preparar o fundo aleatório do Modo Rápido: %s", exc)
        return None, None

    display_name = os.path.splitext(selected)[0].replace("_sem_audio", "")
    return staged_name, display_name

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
        with yt_dlp_operation_lock:
            yt_dlp = load_yt_dlp()
            options = {
                **youtube_download_options(),
                "skip_download": True,
                "socket_timeout": 20,
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
    with yt_dlp_operation_lock:
        yt_dlp = load_yt_dlp()

        # Expurgo prévio obrigatório de downloads completos ou parciais anteriores.
        for filename in os.listdir(cache_dir):
            if filename.startswith("bg_yt_raw.") or filename.startswith("bg_yt_no_audio."):
                try:
                    os.remove(os.path.join(cache_dir, filename))
                except OSError:
                    pass

        base_options = youtube_download_options(os.path.join(cache_dir, "bg_yt_raw.%(ext)s"))
        formats = (
            "bv*[height<=1080]/b[height<=1080]/bv*/b",
            "b/bv*+ba",
        )
        title = "Fundo do YouTube"
        last_error = None
        raw_file = None

        for attempt, media_format in enumerate(formats, start=1):
            options = {
                **base_options,
                "format": media_format,
                "merge_output_format": "mp4",
                "remux_video": "mp4",
            }
            try:
                logger.info("Download do fundo do YouTube: tentativa %s de %s.", attempt, len(formats))
                with yt_dlp.YoutubeDL(options) as ydl:
                    info = ydl.extract_info(url, download=True)
                title = str((info or {}).get("title") or title)
                raw_file = find_downloaded_file(cache_dir, "bg_yt_raw")
                break
            except Exception as exc:
                last_error = exc
                logger.warning("Tentativa %s do fundo do YouTube falhou: %s", attempt, exc)

        if not raw_file:
            raise RuntimeError(f"Não foi possível baixar o fundo do YouTube: {last_error}")

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

    yt_preset_statuses[youtube_status_key(current_user, "audio")] = {
        "status": "starting", "progress": 5, "title": "Identificando vídeo...", "filename": "", "error": None
    }
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

    yt_preset_statuses[youtube_status_key(current_user, "background")] = {
        "status": "starting", "progress": 5, "title": "Identificando vídeo...", "filename": "", "error": None
    }
    threading.Thread(target=run_bg_youtube_download_bg, args=(url, dict(current_user)), daemon=True).start()
    return {"status": "started"}


LRCLIB_API_URL = "https://lrclib.net/api"
LRCLIB_USER_AGENT = "Sal0-Karaoke/9.0.6 (+https://github.com/Sal0-Apps/Sal0-Karaoke)"
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



# Sistema de Logs de Diagnóstico v9.0.6
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
"Sal0 Karaokê v9.0.6 — diagnóstico ao vivo",
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
    library_dirs = [get_user_paths(current_user)["library"]]
    if is_admin(current_user):
        for username, record in load_users().items():
            if record.get("role") != "admin":
                library_dirs.append(get_user_paths({"username": username, "role": record.get("role", "user")})["library"])
    for section in ["videos", "photos", "history"]:
        names = set()
        for library_dir in library_dirs:
            path = os.path.join(library_dir, section)
            if os.path.exists(path):
                try:
                    names.update(f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f)) and not f.startswith('.') and not f.startswith('tmp') and not f.startswith('original_') and not f.startswith('cache_'))
                except Exception as e:
                    logger.error(f"Erro ao listar biblioteca {section}: {e}")
        result[section] = sorted(names)
    return result


def admin_result_owner(owner_key: str, current_user: dict) -> dict:
    require_admin(current_user)
    if owner_key == "__admin__":
        return {"username": current_user.get("username", "admin"), "role": "admin"}
    owner = user_from_username(owner_key)
    if not owner or is_admin(owner):
        raise HTTPException(status_code=404, detail="Perfil não encontrado.")
    return owner


def attachment_file_response(file_path: str, filename: str, media_type: str = None):
    """Entrega downloads com nome UTF-8 e fallback ASCII consistente para Android."""
    safe_name = os.path.basename(str(filename or "download"))
    ascii_name = unicodedata.normalize("NFKD", safe_name).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r'[\x00-\x1f\\/:*?"<>|]', "_", ascii_name).strip(" .") or "download"
    encoded_name = quote(safe_name, safe="")
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'
        ),
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "X-Content-Type-Options": "nosniff",
    }
    resolved_media_type = media_type or mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
    return FileResponse(file_path, media_type=resolved_media_type, headers=headers)


@app.get("/api/admin/results")
def get_admin_results(current_user: dict = Depends(get_current_user)):
    """Lista os vídeos finalizados de todos os perfis com autoria explícita."""
    require_admin(current_user)
    owners = [("__admin__", "Administrador", {"username": current_user.get("username"), "role": "admin"})]
    for username, record in sorted(load_users().items()):
        if record.get("role") != "admin":
            owners.append((username, username, {"username": username, "role": record.get("role", "user")}))

    results = []
    for owner_key, owner_label, owner in owners:
        history_dir = os.path.join(get_user_paths(owner)["library"], "history")
        if not os.path.isdir(history_dir):
            continue
        for filename in os.listdir(history_dir):
            file_path = os.path.join(history_dir, filename)
            if not os.path.isfile(file_path) or filename.startswith("."):
                continue
            stat = os.stat(file_path)
            results.append({
                "owner_key": owner_key,
                "owner": owner_label,
                "filename": filename,
                "kind": "subtitle" if filename.lower().endswith(".srt") else "video",
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            })
    results.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"results": results}


@app.get("/api/admin/results/{owner_key}/{filename}")
def get_admin_result_file(
    owner_key: str,
    filename: str,
    request: Request,
    inline: bool = Query(False),
    current_user: dict = Depends(get_current_user),
):
    owner = admin_result_owner(owner_key, current_user)
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(get_user_paths(owner)["library"], "history", safe_filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Vídeo finalizado não encontrado.")
    if inline:
        media_type = mimetypes.guess_type(file_path)[0] or "video/mp4"
        return inline_file_response(file_path, media_type, request)
    return attachment_file_response(file_path, safe_filename)

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

def resolve_library_file(current_user: dict, section: str, filename: str):
    """Resolve mídias próprias ou, para o administrador, de qualquer usuário."""
    if section not in {"videos", "photos", "history"}:
        return None
    safe = os.path.basename(filename)
    roots = [get_user_paths(current_user)["library"]]
    if is_admin(current_user):
        for username, record in load_users().items():
            if record.get("role") != "admin":
                roots.append(get_user_paths({"username": username, "role": record.get("role", "user")})["library"])
    for root in roots:
        candidate = os.path.join(root, section, safe)
        if os.path.isfile(candidate):
            return candidate, safe
    return None

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

    resolved = resolve_library_file(current_user, section, old_file)
    if resolved:
        target_dir = os.path.dirname(resolved[0])
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
    resolved = resolve_library_file(current_user, section, safe_filename)
    file_path = resolved[0] if resolved else os.path.join(get_user_paths(current_user)["library"], section, safe_filename)

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
    resolved = resolve_library_file(current_user, section, safe_filename)
    file_path = resolved[0] if resolved else os.path.join(get_user_paths(current_user)["library"], section, safe_filename)

    if os.path.exists(file_path):
        return attachment_file_response(file_path, safe_filename)

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
    resolved = resolve_library_file(current_user, section, safe_filename)
    file_path = resolved[0] if resolved else os.path.join(get_user_paths(current_user)["library"], section, safe_filename)
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
    download_name = os.path.basename(record.get("filename") or "sal0_karaoke.mp4")
    return attachment_file_response(file_path, download_name)

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
    cache_dir = queue_cache_dir_for_user(current_user) or get_user_paths(current_user)["cache"]
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
    cache_dir = queue_cache_dir_for_user(current_user) or get_user_paths(current_user)["cache"]
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

    active_pipeline = active_queue_pipeline_for_user(current_user)
    original_video = active_pipeline.get("input_audio_path")
    if active_pipeline.get("subtitle_only") and original_video and check_has_video(original_video):
        media_type = mimetypes.guess_type(original_video)[0] or "video/mp4"
        return FileResponse(original_video, media_type=media_type)

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

    # O item cancelado deixa de existir na fila imediatamente. O worker mantém
    # apenas sua referência privada enquanto encerra o subprocesso e limpa o cache.
    with processing_queue_lock:
        active_job = next(
            (
                job for job in processing_queue
                if job.get("status") == "processing"
                and (
                    is_admin(current_user)
                    or job.get("owner_username") == current_user.get("username")
                )
            ),
            None,
        )
        if active_job:
            processing_queue.remove(active_job)
            save_processing_queue_unlocked()

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
    processing_queue_event.set()

    # O worker libera o lock no bloco finally, depois de realmente encerrar.
    return {"status": "success", "message": "Processamento cancelado com sucesso."}

@app.get("/", response_class=HTMLResponse)
def read_index():
    """Serve a interface gráfica web da aplicação."""
    # Retorna o arquivo de template HTML compilado com Jinja2
    # Como não temos variáveis dinâmicas de renderização inicial, passamos apenas o contexto vazio
    return templates.TemplateResponse("index.html", {"request": {}})

@app.get("/api/status")
def get_status(response: Response, current_user: dict = Depends(get_current_user)):
    """Retorna o progresso atual sem permitir que o navegador reutilize estado antigo."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
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
    easy_mode: bool = Form(False),
    easy_background_choice: str = Form("default"),
    subtitle_only: bool = Form(False),
    translation_language: str = Form("pt")
):
    """
    Recebe os arquivos enviados, valida a concorrência e inicia o pipeline em segundo plano.
    """
    ensure_processing_queue_access(current_user)
    ensure_processing_queue_capacity(current_user.get("username"))
    translation_language = (translation_language or "pt").strip().lower()
    if translation_language not in SUPPORTED_TARGET_LANGUAGES:
        raise HTTPException(status_code=400, detail="Idioma de tradução inválido.")
    quick_random_background_requested = False
    quick_background_title = ""
    if easy_mode:
        easy_config = load_easy_mode_config()
        if not easy_config.get("enabled", True):
            raise HTTPException(status_code=403, detail="O Modo Rápido foi desativado pelo administrador.")
        whisper_model = easy_config["whisper_model"]
        font_size = easy_config["font_size"]
        text_color = easy_config["text_color"]
        text_position = easy_config["text_position"]
        subtitle_mode = easy_config["subtitle_mode"]
        words_per_line = easy_config["words_per_line"]
        max_chars_line = easy_config["max_chars_line"]
        break_on_punctuation = easy_config["break_on_punctuation"]
        enable_vad = easy_config["enable_vad"]
        transcription_preset = easy_config["transcription_preset"]
        configured_background = easy_config["background_mode"]
        easy_background_choice = (easy_background_choice or "default").strip().lower()
        if easy_background_choice not in {"default", "original"}:
            easy_background_choice = "default"
        has_explicit_background = bool((bg_file and bg_file.filename) or library_bg)
        quick_random_background_requested = bool(
            not has_explicit_background
            and easy_background_choice != "original"
            and configured_background == "random_library"
        )
        if has_explicit_background:
            background_mode = "image"
        elif easy_background_choice == "original":
            background_mode = "original"
        elif configured_background in {"image", "random_library"}:
            background_mode = "original"
        else:
            background_mode = configured_background
        show_instrumental = easy_config["show_instrumental"]
        transcribe_source = easy_config["transcribe_source"]
        show_next_line_preview = easy_config["show_next_line_preview"]
        lyrics_text = None
        lyrics_mode = easy_config["lyrics_mode"]
        enable_correction = easy_config["enable_correction"]
        keep_first_line_visible = easy_config["keep_first_line_visible"]
        pause_for_editing = False
        save_to_library = easy_config["save_to_library"]
        only_remove_vocals = easy_config["only_remove_vocals"]

    if subtitle_only:
        background_mode = "original"
        transcribe_source = "original"
        show_instrumental = False
        show_next_line_preview = False
        lyrics_mode = "manual"
        lyrics_text = ""
        only_remove_vocals = False

    if transcription_preset not in {"karaoke", "continuous", "difficult", "fast"}:
        raise HTTPException(status_code=400, detail="Perfil de leitura da voz inválido.")

    user_paths = get_user_paths(current_user)
    job_id = uuid.uuid4().hex
    cache_dir = os.path.join(PROCESSING_QUEUE_ROOT, job_id, "cache")
    library_dir = user_paths["library"]
    os.makedirs(cache_dir, exist_ok=True)
    cache_meta_file = os.path.join(cache_dir, "cache_meta.json")

    has_new_source = bool(
        (youtube_url and youtube_url.strip())
        or (library_audio and library_audio.strip())
        or (audio_file and audio_file.filename and audio_file.filename.strip())
    )
    if not has_new_source:
        legacy_cache_dir = user_paths["cache"]
        if os.path.isdir(legacy_cache_dir):
            shutil.copytree(legacy_cache_dir, cache_dir, dirs_exist_ok=True)

    if quick_random_background_requested:
        library_bg, quick_background_title = stage_quick_random_background(easy_config, current_user)
        if library_bg:
            background_mode = "image"
        else:
            background_mode = "original"

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

        if not os.path.exists(lib_audio_path) and is_admin(current_user):
            for username, record in load_users().items():
                candidate_dir = os.path.join(get_user_paths({"username": username, "role": record.get("role", "user")})["library"], "videos")
                candidate = os.path.join(candidate_dir, library_audio)
                if os.path.isfile(candidate):
                    lib_video_dir, lib_audio_path = candidate_dir, candidate
                    break

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

    model_labels = {
        "large-v3-turbo": "Large V3 Turbo",
        "large-v3": "Large V3",
        "medium": "Medium",
        "small": "Small",
        "tiny": "Tiny",
    }
    if lyrics_mode == "auto":
        lyrics_summary = "Buscando letra-guia"
    elif (lyrics_text or "").strip():
        lyrics_summary = "Letra manual + Whisper"
    else:
        lyrics_summary = "Somente Whisper"

    if quick_background_title:
        background_summary = f"Fundo surpresa: {quick_background_title}"
    elif library_bg:
        background_summary = os.path.splitext(os.path.basename(library_bg))[0].replace("_sem_audio", "")
    elif bg_file and bg_file.filename:
        background_summary = os.path.splitext(bg_file.filename)[0]
    elif background_mode == "original":
        background_summary = "Vídeo original"
    elif background_mode == "color":
        background_summary = "Cor sólida"
    else:
        background_summary = "Visual padrão"

    process_summary = {
        "title": orig_name,
        "lyrics": (
            f"SRT · {translation_language.upper() if translation_language != 'original' else 'idioma original'}"
            if subtitle_only else lyrics_summary
        ),
        "model": model_labels.get(whisper_model, whisper_model),
        "mode": "Gerar SRT" if subtitle_only else ("Modo Rápido" if easy_mode else "Modo Detalhado"),
        "background": "Somente arquivos SRT" if subtitle_only else background_summary,
    }

    pipeline = {
        "input_audio_path": input_audio_path,
        "input_bg_path": input_bg_path,
        "whisper_model": whisper_model,
        "font_size": font_size,
        "text_color": text_color,
        "text_position": text_position,
        "subtitle_mode": subtitle_mode,
        "words_per_line": words_per_line,
        "max_chars_line": max_chars_line,
        "break_on_punctuation": break_on_punctuation,
        "enable_vad": enable_vad,
        "transcription_preset": transcription_preset,
        "background_mode": background_mode,
        "show_instrumental": show_instrumental,
        "transcribe_source": transcribe_source,
        "show_next_line_preview": show_next_line_preview,
        "lyrics_text": lyrics_text,
        "lyrics_mode": lyrics_mode,
        "enable_correction": enable_correction,
        "keep_first_line_visible": keep_first_line_visible,
        "youtube_url": youtube_url,
        "only_remove_vocals": only_remove_vocals,
        "owner_user": dict(current_user),
        "cache_dir": cache_dir,
        "output_dir": user_paths["output"],
        "library_dir": library_dir,
        "app_base_url": (app_base_url or "").strip(),
        "subtitle_only": subtitle_only,
        "translation_language": translation_language,
    }
    job = {
        "id": job_id,
        "title": orig_name,
        "owner_username": current_user.get("username"),
        "owner_role": current_user.get("role"),
        "status": "queued",
        "message": "Aguardando processamento.",
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
        "process_summary": process_summary,
        "pipeline": pipeline,
    }
    try:
        position = enqueue_processing_job(job)
    except Exception:
        remove_finished_queue_cache(cache_dir)
        raise
    return {"status": "queued", "job_id": job_id, "position": position, "title": orig_name}

def compress_video_for_telegram(source_path: str, destination_path: str, target_bytes: int) -> bool:
    """Cria uma prévia completa sob o limite do bot sem alterar o resultado original."""
    duration = get_file_duration(source_path)
    if duration <= 0:
        return False
    total_kbps = max(32, int((target_bytes * 8 * 0.92) / duration / 1000))
    audio_kbps = 48 if total_kbps >= 120 else 24
    video_kbps = max(12, total_kbps - audio_kbps)
    height = 720 if video_kbps >= 700 else (480 if video_kbps >= 300 else 360)

    with tempfile.TemporaryDirectory(prefix="sal0-telegram-") as pass_dir:
        pass_log = os.path.join(pass_dir, "encode")
        for attempt in range(3):
            attempt_video_kbps = max(10, int(video_kbps * (0.82 ** attempt)))
            common_video = [
                "-vf", f"scale=-2:'min({height},ih)'",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-b:v", f"{attempt_video_kbps}k",
                "-maxrate", f"{attempt_video_kbps}k",
                "-bufsize", f"{max(20, attempt_video_kbps * 2)}k",
                "-pix_fmt", "yuv420p",
            ]
            first_pass = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", source_path,
                    *common_video,
                    "-pass", "1", "-passlogfile", pass_log,
                    "-an", "-f", "null", os.devnull,
                ],
                capture_output=True,
                text=True,
                timeout=21600,
                check=False,
            )
            if first_pass.returncode != 0:
                logger.error("Primeira passagem da prévia Telegram falhou: %s", first_pass.stderr[-1000:])
                return False
            second_pass = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", source_path,
                    *common_video,
                    "-pass", "2", "-passlogfile", pass_log,
                    "-c:a", "aac", "-b:a", f"{audio_kbps}k",
                    "-movflags", "+faststart", destination_path,
                ],
                capture_output=True,
                text=True,
                timeout=21600,
                check=False,
            )
            if second_pass.returncode == 0 and os.path.isfile(destination_path):
                if 0 < os.path.getsize(destination_path) <= target_bytes:
                    return True
                logger.warning("Prévia Telegram ainda excedeu o limite; reduzindo a taxa de bits.")
            else:
                logger.error("Segunda passagem da prévia Telegram falhou: %s", second_pass.stderr[-1000:])
                return False
    return False


def send_telegram_video_flow(
    token: str,
    chat_id: str,
    video_path: str,
    orig_name: str,
    history_filename: str,
    public_download_token: str,
    base_url: str = "",
    external_url: str = "",
    processing_seconds: float = 0,
):
    """Envia o vídeo e links diretos sem reutilizar a sessão web do usuário."""
    if not token or not chat_id:
        return

    limit_50mb = 50 * 1024 * 1024
    compressed_target = 46 * 1024 * 1024
    duration_text = format_processing_duration(processing_seconds)

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
        success = False
        sent_compressed_preview = False
        with tempfile.TemporaryDirectory(prefix="sal0-telegram-preview-") as preview_dir:
            upload_path = video_path
            if file_size > limit_50mb:
                upload_path = os.path.join(preview_dir, "preview_telegram.mp4")
                sent_compressed_preview = compress_video_for_telegram(
                    video_path,
                    upload_path,
                    compressed_target,
                )
                if not sent_compressed_preview:
                    upload_path = ""

            if upload_path:
                with open(upload_path, "rb") as video_file:
                    response = requests.post(
                        f"https://api.telegram.org/bot{token}/sendVideo",
                        data={
                            "chat_id": chat_id,
                            "caption": (
                                f"🎥 <b>Sal0 Karaokê</b>: prévia compactada de <b>{orig_name}</b>\n"
                                f"⏱ Tempo total de processamento: <b>{duration_text}</b>"
                                if sent_compressed_preview
                                else f"🎥 <b>Sal0 Karaokê</b>: aqui está <b>{orig_name}</b>!\n"
                                f"⏱ Tempo total de processamento: <b>{duration_text}</b>"
                            ),
                            "parse_mode": "HTML",
                        },
                        files={"video": (os.path.basename(upload_path), video_file, "video/mp4")},
                        timeout=300,
                    )
                    success = response.status_code == 200
                    if not success:
                        logger.error("Telegram recusou o vídeo com HTTP %s.", response.status_code)

        if success and sent_compressed_preview:
            status_text = "Prévia compactada enviada; o original permanece intacto na Biblioteca."
        elif success:
            status_text = "Vídeo original enviado e salvo na sua Biblioteca."
        else:
            status_text = "Não foi possível anexar a prévia, mas o original está salvo na sua Biblioteca."
        send_telegram_notification(
            token,
            chat_id,
            f"✅ <b>Sal0 Karaokê</b>: <b>{orig_name}</b> concluído. {status_text}\n"
            f"⏱ Tempo total de processamento: <b>{duration_text}</b>.\n"
            f"Use os links abaixo para baixar o arquivo original sem compressão.{download_block}"
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
    external_url: str,
    processing_seconds: float = 0,
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
                "external_url": external_url,
                "processing_seconds": processing_seconds,
            },
            daemon=True
        ).start()


def send_telegram_document_flow(
    token: str,
    chat_id: str,
    document_path: str,
    display_name: str,
    public_download_token: str,
    base_url: str = "",
    external_url: str = "",
    processing_seconds: float = 0,
):
    """Envia um resultado leve como documento e sempre publica os links disponíveis."""
    if not token or not chat_id or not os.path.isfile(document_path):
        return
    route = f"/api/public/download/{public_download_token}" if public_download_token else ""
    links = []
    duration_text = format_processing_duration(processing_seconds)
    if route and base_url.strip():
        links.append(f'🏠 <a href="{base_url.rstrip("/")}{route}">Baixar na rede local</a>')
    if route and external_url.strip():
        links.append(f'🌐 <a href="{external_url.rstrip("/")}{route}">Baixar pelo acesso externo</a>')

    success = False
    try:
        with open(document_path, "rb") as document_file:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={
                    "chat_id": chat_id,
                    "caption": (
                        f"📄 <b>Sal0 Karaokê</b>: {display_name}\n"
                        f"⏱ Tempo total de processamento: <b>{duration_text}</b>"
                    ),
                    "parse_mode": "HTML",
                },
                files={"document": (os.path.basename(document_path), document_file, "application/x-subrip")},
                timeout=90,
            )
            success = response.ok
            if not success:
                logger.error("Telegram recusou o documento com HTTP %s.", response.status_code)
    except Exception as exc:
        logger.error("Falha ao enviar documento ao Telegram: %s", exc)

    delivery = "Arquivo SRT enviado diretamente." if success else "O envio direto falhou; use um dos links abaixo."
    link_block = "\n" + "\n".join(links) if links else ""
    send_telegram_notification(
        token,
        chat_id,
        f"✅ <b>Sal0 Karaokê</b>: {display_name}. {delivery}\n"
        f"⏱ Tempo total de processamento: <b>{duration_text}</b>.{link_block}",
    )


def send_documents_to_targets(
    targets: list[dict],
    documents: list[dict],
    base_url: str,
    external_url: str,
    processing_seconds: float = 0,
):
    for target in targets:
        for document in documents:
            threading.Thread(
                target=send_telegram_document_flow,
                kwargs={
                    "token": target["telegram_token"],
                    "chat_id": target["telegram_chat_id"],
                    "document_path": document["path"],
                    "display_name": document["label"],
                    "public_download_token": document.get("public_download_token"),
                    "base_url": base_url,
                    "external_url": external_url,
                    "processing_seconds": processing_seconds,
                },
                daemon=True,
            ).start()


def run_subtitle_srt_pipeline(
    input_media_path: str,
    orig_name: str,
    whisper_model: str,
    enable_vad: bool,
    transcription_preset: str,
    enable_correction: bool,
    translation_language: str,
    owner_user: dict,
    cache_dir: str,
    output_dir: str,
    library_dir: str,
    telegram_targets: list[dict],
    telegram_base_url: str = "",
    telegram_external_url: str = "",
    processing_elapsed_callback=None,
):
    """Transcreve qualquer mídia por MP3 e retorna somente SRT original/traduzido."""
    import process_manager as pm

    os.makedirs(output_dir, exist_ok=True)
    normalized_mp3 = os.path.join(cache_dir, "subtitle_source.mp3")
    segments_cache_file = os.path.join(cache_dir, "subtitle_segments_original.json")
    info_cache_file = os.path.join(cache_dir, "subtitle_info_original.json")
    final_original_srt = os.path.join(output_dir, "final_subtitles_original.srt")
    final_translated_srt = os.path.join(output_dir, "final_subtitles_translated.srt")
    cache_signature = {
        "whisper_model": whisper_model,
        "enable_vad": bool(enable_vad),
        "transcription_preset": transcription_preset,
    }

    pm.check_cancelled()
    if not os.path.isfile(normalized_mp3):
        update_state("processing", "Converting media to MP3", 15)
        extract_audio_mp3(input_media_path, normalized_mp3)
    else:
        update_state("processing", "Using normalized MP3", 15)
    media_duration = get_file_duration(normalized_mp3)
    if media_duration <= 0:
        raise ValueError("Não foi possível determinar a duração do áudio normalizado.")
    save_stage_checkpoint(cache_dir, "subtitle_audio_ready", "áudio normalizado para MP3", 20)

    original_segments = None
    transcription_info = {}
    if os.path.isfile(segments_cache_file) and os.path.isfile(info_cache_file):
        try:
            with open(segments_cache_file, "r", encoding="utf-8") as segment_file:
                original_segments = json.load(segment_file)
            with open(info_cache_file, "r", encoding="utf-8") as info_file:
                transcription_info = json.load(info_file)
            if transcription_info.get("cache_signature") != cache_signature:
                original_segments = None
            else:
                update_state("processing", "Using cached transcription", 65)
        except (OSError, ValueError):
            original_segments = None

    if original_segments is None:
        pm.check_cancelled()
        update_state(
            "processing",
            "Transcribing complete MP3",
            45,
            stage_progress=0,
            stage_detail="Carregando o modelo Whisper e preparando o áudio",
        )
        notify_targets(
            telegram_targets,
            f"✍️ <b>Sal0 Karaokê</b>: Transcrevendo o áudio completo de <b>{orig_name}</b>.",
        )
        def publish_subtitle_whisper_progress(percent: int, elapsed: float, total: float):
            remaining = max(0.0, total - elapsed)
            detail = f"Whisper {percent}%"
            if total > 0:
                detail += f" · {int(elapsed // 60):02d}:{int(elapsed % 60):02d} de {int(total // 60):02d}:{int(total % 60):02d}"
                if remaining > 0:
                    detail += f" · faltam {int(remaining // 60):02d}:{int(remaining % 60):02d} de áudio"
            update_state(
                "processing",
                "Transcribing complete MP3",
                min(69, 45 + round(percent * 0.24)),
                stage_progress=percent,
                stage_detail=detail,
            )

        original_segments, transcription_info = transcribe_vocals(
            normalized_mp3,
            model_size=whisper_model,
            quality_mode="max_quality" if whisper_model == "large-v3" else "standard",
            enable_vad=enable_vad,
            transcription_preset=transcription_preset,
            task="transcribe",
            return_info=True,
            progress_callback=publish_subtitle_whisper_progress,
        )
        if original_segments:
            transcription_info["cache_signature"] = cache_signature
            with open(segments_cache_file, "w", encoding="utf-8") as segment_file:
                json.dump(original_segments, segment_file, ensure_ascii=False, indent=2)
            with open(info_cache_file, "w", encoding="utf-8") as info_file:
                json.dump(transcription_info, info_file, ensure_ascii=False, indent=2)

    if not original_segments:
        raise ValueError("Nenhuma fala foi detectada na mídia enviada.")

    save_stage_checkpoint(cache_dir, "subtitle_transcription_ready", "transcrição do Whisper concluída", 69)

    pm.check_cancelled()
    review_checkpoint = stage_checkpoint(cache_dir, "subtitle_transcription_reviewed")
    if enable_correction and not review_checkpoint:
        global segments_to_edit, correction_event
        segments_to_edit = original_segments
        correction_event.clear()
        update_state("waiting_for_user_correction", "Correction", 68)
        while not correction_event.is_set():
            pm.check_cancelled()
            if queue_pause_requested():
                save_stage_checkpoint(
                    cache_dir,
                    "subtitle_transcription_ready",
                    "transcrição do Whisper concluída",
                    69,
                )
            correction_event.wait(timeout=1.0)
        original_segments = segments_to_edit
        with open(segments_cache_file, "w", encoding="utf-8") as segment_file:
            json.dump(original_segments, segment_file, ensure_ascii=False, indent=2)
        save_stage_checkpoint(
            cache_dir,
            "subtitle_transcription_reviewed",
            "revisão da transcrição concluída",
            70,
        )
    elif review_checkpoint:
        update_state("processing", "Using reviewed transcription checkpoint", 70)

    original_segments = cover_full_media_timeline(original_segments, media_duration)
    original_checkpoint = stage_checkpoint(cache_dir, "subtitle_original_ready")
    original_filename = str(original_checkpoint.get("filename") or "")
    original_library_path = os.path.join(library_dir, "history", original_filename) if original_filename else ""
    if original_filename and os.path.isfile(original_library_path):
        if not os.path.isfile(final_original_srt):
            shutil.copy2(original_library_path, final_original_srt)
        update_state("processing", "Using original SRT checkpoint", 75)
    else:
        update_state("processing", "Generating original SRT", 72)
        write_srt(original_segments, final_original_srt)
        original_filename = save_srt_result(
            final_original_srt,
            orig_name,
            library_dir,
            transcription_info.get("language") or "original",
        )
    if not original_filename:
        raise RuntimeError("Não foi possível salvar o SRT original na Biblioteca.")
    save_stage_checkpoint(
        cache_dir,
        "subtitle_original_ready",
        "SRT original salvo",
        75,
        filename=original_filename,
    )

    translated_filename = None
    translation_error = ""
    source_language = str(transcription_info.get("language") or "").split("-")[0].lower()
    translation_checkpoint = stage_checkpoint(cache_dir, "subtitle_translation_finished")
    checkpoint_translation_filename = str(translation_checkpoint.get("filename") or "")
    checkpoint_translation_path = (
        os.path.join(library_dir, "history", checkpoint_translation_filename)
        if checkpoint_translation_filename else ""
    )
    if translation_checkpoint:
        translation_error = str(translation_checkpoint.get("error") or "")
        if checkpoint_translation_filename and os.path.isfile(checkpoint_translation_path):
            translated_filename = checkpoint_translation_filename
            if not os.path.isfile(final_translated_srt):
                shutil.copy2(checkpoint_translation_path, final_translated_srt)
        update_state("processing", "Using translation checkpoint", 95)
    elif translation_language != "original":
        try:
            update_state(
                "processing",
                "Translating optional SRT",
                80,
                stage_progress=0,
                stage_detail="O SRT original já está seguro na Biblioteca",
            )

            def translation_progress(completed: int, total: int):
                percent = round((completed / max(total, 1)) * 100)
                update_state(
                    "processing",
                    "Translating optional SRT",
                    80 + round(percent * 0.15),
                    stage_progress=percent,
                    stage_detail=f"{completed} de {total} trechos traduzidos",
                )

            translated_segments = translate_subtitle_segments(
                original_segments,
                source_language=source_language,
                target_language=translation_language,
                progress_callback=translation_progress,
            )
            translated_segments = cover_full_media_timeline(translated_segments, media_duration)
            write_srt(translated_segments, final_translated_srt)
            translated_filename = save_srt_result(
                final_translated_srt,
                orig_name,
                library_dir,
                translation_language,
            )
        except Exception as exc:
            translation_error = str(exc)
            logger.exception("A tradução opcional falhou; o SRT original foi preservado.")
            notify_targets(
                telegram_targets,
                f"⚠️ <b>Sal0 Karaokê</b>: o SRT original de <b>{orig_name}</b> ficou pronto, "
                "mas a tradução opcional falhou.",
            )
    save_stage_checkpoint(
        cache_dir,
        "subtitle_translation_finished",
        "tradução opcional concluída" if translated_filename else "etapa de tradução encerrada",
        95,
        filename=translated_filename or "",
        error=translation_error,
    )

    primary_subtitle = translated_filename or original_filename
    public_token = create_public_download(owner_user, original_filename)
    translated_public_token = create_public_download(owner_user, translated_filename) if translated_filename else None
    save_result_metadata(
        output_dir,
        orig_name,
        original_filename,
        subtitle_filename=primary_subtitle,
        subtitle_language=translation_language,
        original_subtitle_filename=original_filename,
        translated_subtitle_filename=translated_filename,
        translation_error=translation_error,
        result_kind="subtitles",
    )
    total_processing_seconds = (
        processing_elapsed_callback() if processing_elapsed_callback else 0
    )
    update_state(
        "done",
        "SRT ready",
        100,
        result_file=final_original_srt,
        history_filename=original_filename,
        subtitle_filename=primary_subtitle,
        original_subtitle_filename=original_filename,
        translated_subtitle_filename=translated_filename or "",
        subtitle_language=translation_language,
        translation_error=translation_error,
        result_kind="subtitles",
        public_download_token=public_token,
    )
    completion = "SRT original e traduzido" if translated_filename else "SRT original"
    telegram_documents = [{
        "path": os.path.join(library_dir, "history", original_filename),
        "label": f"SRT original de {orig_name}",
        "public_download_token": public_token,
    }]
    if translated_filename:
        telegram_documents.append({
            "path": os.path.join(library_dir, "history", translated_filename),
            "label": f"SRT traduzido de {orig_name}",
            "public_download_token": translated_public_token,
        })
    send_documents_to_targets(
        telegram_targets,
        telegram_documents,
        telegram_base_url,
        telegram_external_url,
        total_processing_seconds,
    )
    logger.info("%s concluído(s) e encaminhado(s) ao Telegram.", completion)

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
    app_base_url: str = "",
    subtitle_only: bool = False,
    translation_language: str = "pt",
):
    """Pipeline principal de processamento sequencial."""
    # Obter o lock de processamento exclusivo (segurança de job único)
    if not processing_lock.acquire(blocking=False):
        logger.warning("Bloqueio de concorrência ativado: Processamento já em andamento.")
        raise RuntimeError("O processador não foi liberado pelo trabalho anterior.")

    owner_user = owner_user or {"username": state.get("owner_username"), "role": state.get("owner_role", "user")}
    owner_paths = get_user_paths(owner_user)
    cache_dir = cache_dir or owner_paths["cache"]
    output_dir = output_dir or owner_paths["output"]
    library_dir = library_dir or owner_paths["library"]
    saved_lyrics_file = os.path.join(output_dir, "saved_lyrics.txt")
    telegram_targets = get_notification_targets(owner_user)
    os.makedirs(cache_dir, exist_ok=True)
    previous_processing_seconds = float(
        load_stage_checkpoints(cache_dir).get("active_processing_seconds") or 0
    )
    active_run_started = time.monotonic()

    def persist_total_processing_seconds() -> float:
        elapsed = previous_processing_seconds + (time.monotonic() - active_run_started)
        return persist_active_processing_seconds(cache_dir, elapsed)

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
        final_srt_path = os.path.join(output_dir, "final_subtitles.srt")
        final_original_srt_path = os.path.join(output_dir, "final_subtitles_original.srt")
        final_translated_srt_path = os.path.join(output_dir, "final_subtitles_translated.srt")

        os.makedirs(cache_dir, exist_ok=True)
        completed_checkpoints = load_stage_checkpoints(cache_dir).get("completed_stages", {})

        # Preservar resultados de etapas concluídas para permitir retomada após reinício.
        if "video_rendered" not in completed_checkpoints and os.path.exists(final_mp4_path):
            os.remove(final_mp4_path)
        if "subtitles_generated" not in completed_checkpoints and os.path.exists(final_ass_path):
            os.remove(final_ass_path)
        if os.path.exists(final_srt_path):
            os.remove(final_srt_path)
        if "subtitle_original_ready" not in completed_checkpoints and os.path.exists(final_original_srt_path):
            os.remove(final_original_srt_path)
        if "subtitle_translation_finished" not in completed_checkpoints and os.path.exists(final_translated_srt_path):
            os.remove(final_translated_srt_path)

        # Configurar diretório de cache persistente
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

        if subtitle_only:
            logger.info("Modo Gerar SRT ativo: Demucs desativado; usando somente o áudio original e o Whisper.")
            run_subtitle_srt_pipeline(
                input_media_path=input_audio_path,
                orig_name=orig_name,
                whisper_model=whisper_model,
                enable_vad=enable_vad,
                transcription_preset=transcription_preset,
                enable_correction=enable_correction,
                translation_language=translation_language,
                owner_user=owner_user,
                cache_dir=cache_dir,
                output_dir=output_dir,
                library_dir=library_dir,
                telegram_targets=telegram_targets,
                telegram_base_url=telegram_base_url,
                telegram_external_url=telegram_external_url,
                processing_elapsed_callback=persist_total_processing_seconds,
            )
            return

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
                update_process_summary(lyrics="Letra-guia + Whisper")
                notify_targets(
                    telegram_targets,
                    f"📖 <b>Sal0 Karaokê</b>: letra-guia encontrada para <b>{orig_name}</b>.",
                )
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
                update_process_summary(lyrics="Somente Whisper")
                notify_targets(
                    telegram_targets,
                    f"📖 <b>Sal0 Karaokê</b>: nenhuma letra-guia foi encontrada para <b>{orig_name}</b>; "
                    "o processamento seguirá somente com o Whisper.",
                )
                logger.info("Seguindo sem letra guia automática para '%s'.", orig_name)
        elif lyrics_text:
            notify_targets(
                telegram_targets,
                f"📖 <b>Sal0 Karaokê</b>: letra-guia manual recebida para <b>{orig_name}</b>.",
            )
        else:
            notify_targets(
                telegram_targets,
                f"📖 <b>Sal0 Karaokê</b>: <b>{orig_name}</b> será processado sem letra-guia.",
            )

        # Invalidação Inteligente de Cache: comparar o hash/tamanho do arquivo de entrada atual com o cache
        new_audio_hash = None
        try:
            if os.path.exists(input_audio_path):
                new_audio_hash = f"{os.path.basename(input_audio_path)}_{os.path.getsize(input_audio_path)}"
        except Exception:
            pass

        cached_audio_hash = cached_meta.get("audio_hash")
        if new_audio_hash and cached_audio_hash != new_audio_hash:
            logger.info(f"Nova mídia detectada para processamento ({orig_name}). Limpando cache de áudio anterior...")
            for inter_file in [
                "original_converted.wav",
                "vocals.wav",
                "instrumental.wav",
                "transcribed_segments.json",
                "karaoke.ass",
                "stage_checkpoints.json",
            ]:
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

        save_stage_checkpoint(cache_dir, "input_ready", "entrada preparada", 10)

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
            save_stage_checkpoint(cache_dir, "audio_extracted", "áudio extraído", 15)

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
                    stage_detail="Preparando quatro análises locais de alta precisão"
                )
                notify_targets(telegram_targets, "✂️ <b>Sal0 Karaokê</b>: Iniciando a separação local de vocais")
                with tempfile.TemporaryDirectory() as demucs_tmp:
                    v_tmp, i_tmp = separate_vocals(converted_wav, demucs_tmp, update_callback=update_state)
                    shutil.move(v_tmp, vocals_wav)
                    shutil.move(i_tmp, instrumental_wav)

            pm.check_cancelled()
            save_stage_checkpoint(cache_dir, "vocals_separated", "vocais separados pelo Demucs", 55)

            def publish_render_progress(percent: int):
                update_state(
                    "processing",
                    "Rendering final video",
                    min(98, 95 + round(percent * 0.03)),
                    stage_progress=percent,
                    stage_detail="Codificando o vídeo final",
                )

            # Se only_remove_vocals estiver ativo, pulamos transcrição e legenda, indo direto para renderização
            if only_remove_vocals:
                pm.check_cancelled()
                rendered_checkpoint = stage_checkpoint(cache_dir, "video_rendered")
                if not rendered_checkpoint or not os.path.isfile(final_mp4_path):
                    update_state("processing", "Rendering final video", 95)
                    notify_targets(telegram_targets, "🎬 <b>Sal0 Karaokê</b>: Renderizando vídeo sem a voz do cantor (95%)")

                    # Forçar o uso do vídeo original enviado
                    render_karaoke_video(
                        instrumental_path=instrumental_wav,
                        ass_path=None,
                        output_mp4_path=final_mp4_path,
                        background_image_path=None,
                        original_video_path=input_audio_path,
                        background_mode="original_video",
                        progress_callback=publish_render_progress,
                    )
                else:
                    update_state("processing", "Using rendered video checkpoint", 98)

                pm.check_cancelled()
                save_stage_checkpoint(cache_dir, "video_rendered", "vídeo renderizado", 98)
                history_filename = save_video_to_history(final_mp4_path, orig_name, library_dir)
                public_token = create_public_download(owner_user, history_filename)
                save_result_metadata(output_dir, orig_name, history_filename)
                total_processing_seconds = persist_total_processing_seconds()
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
                    telegram_external_url,
                    total_processing_seconds,
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
                    update_state(
                        "processing",
                        "Transcribing vocals (cached)",
                        70,
                        stage_progress=100,
                        stage_detail="Transcrição recuperada do cache",
                    )
                except Exception as e:
                    logger.error(f"Erro ao ler cache de segmentos transcritos: {e}")

            if segments is None:
                pm.check_cancelled()
                update_state(
                    "processing",
                    "Transcribing vocals",
                    65,
                    stage_progress=0,
                    stage_detail="Carregando o modelo Whisper e preparando o áudio",
                )
                notify_targets(telegram_targets, f"✍️ <b>Sal0 Karaokê</b>: Transcrevendo voz ({whisper_model}) (70%)")

                transcribe_audio = vocals_wav if transcribe_source == "vocals" else converted_wav
                logger.info(f"Fonte de transcrição escolhida: {transcribe_audio} (Modo: {transcribe_source})")

                # Verificar status do modelo Whisper com is_model_downloaded() para exibir a mensagem correta na UI
                if is_model_downloaded(whisper_model):
                    update_state(
                        "processing",
                        f"Carregando Modelo Whisper {whisper_model} do disco e transcrevendo voz...",
                        65,
                        stage_progress=0,
                        stage_detail="Carregando o modelo Whisper do armazenamento local",
                    )
                else:
                    update_state(
                        "processing",
                        f"Baixando Modelo de IA Whisper {whisper_model} no servidor...",
                        65,
                        stage_progress=0,
                        stage_detail="Baixando o modelo Whisper antes da transcrição",
                    )

                quality_preset = "max_quality" if whisper_model == "large-v3" else "standard"
                def publish_whisper_progress(percent: int, elapsed: float, total: float):
                    remaining = max(0.0, total - elapsed)
                    detail = f"Whisper {percent}%"
                    if total > 0:
                        detail += f" · {int(elapsed // 60):02d}:{int(elapsed % 60):02d} de {int(total // 60):02d}:{int(total % 60):02d}"
                        if remaining > 0:
                            detail += f" · faltam {int(remaining // 60):02d}:{int(remaining % 60):02d} de áudio"
                    update_state(
                        "processing",
                        "Transcribing vocals",
                        min(74, 65 + round(percent * 0.09)),
                        stage_progress=percent,
                        stage_detail=detail,
                    )

                segments = transcribe_vocals(
                    transcribe_audio,
                    model_size=whisper_model,
                    initial_prompt=lyrics_text,
                    quality_mode=quality_preset,
                    enable_vad=enable_vad,
                    transcription_preset=transcription_preset,
                    progress_callback=publish_whisper_progress,
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

            save_stage_checkpoint(cache_dir, "transcription_ready", "transcrição do Whisper concluída", 74)

            # A letra corrige apenas a grafia; os tempos continuam vindo do áudio.
            if lyrics_text and lyrics_text.strip():
                logger.info("Aplicando letra guia de forma conservadora, sem criar timestamps...")
                segments = align_lyrics(lyrics_text, segments)

            pm.check_cancelled()

            # --- NOVO: Passo de Pausa e Correção de Legendas (se ativado pelo usuário) ---
            review_checkpoint = stage_checkpoint(cache_dir, "transcription_reviewed")
            if enable_correction and not review_checkpoint:
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
                    if queue_pause_requested():
                        save_stage_checkpoint(
                            cache_dir,
                            "transcription_ready",
                            "transcrição do Whisper concluída",
                            74,
                        )
                    correction_event.wait(timeout=1.0)

                logger.info("Retomando o processamento com as legendas corrigidas.")
                segments = segments_to_edit

                # Salvar os segmentos corrigidos também no cache, para não perder o trabalho se refazer!
                with open(segments_cache_file, "w", encoding="utf-8") as f:
                    import json
                    json.dump(segments, f, indent=4)

                save_stage_checkpoint(cache_dir, "transcription_reviewed", "revisão das legendas concluída", 78)
            elif review_checkpoint:
                update_state("processing", "Using reviewed subtitle checkpoint", 78)

            pm.check_cancelled()

            # Passo 4: Gerar legendas ASS com efeitos de karaokê
            ass_path = os.path.join(cache_dir, "karaoke.ass")
            subtitles_checkpoint = stage_checkpoint(cache_dir, "subtitles_generated")
            if not subtitles_checkpoint or not os.path.isfile(ass_path):
                update_state("processing", "Generating subtitles", 80)
                notify_targets(telegram_targets, "📝 <b>Sal0 Karaokê</b>: Gerando legenda (80%)")
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
            else:
                update_state("processing", "Using subtitle checkpoint", 80)

            pm.check_cancelled()
            save_stage_checkpoint(cache_dir, "subtitles_generated", "legendas geradas", 80)

            # Passo 5: Renderizar o vídeo final
            rendered_checkpoint = stage_checkpoint(cache_dir, "video_rendered")
            if not rendered_checkpoint or not os.path.isfile(final_mp4_path):
                update_state("processing", "Rendering final video", 95)
                notify_targets(telegram_targets, "🎬 <b>Sal0 Karaokê</b>: Renderizando vídeo (95%)")
                bg_mode_param = "original_video" if (background_mode in ["original", "original_video"]) else background_mode
                render_karaoke_video(
                    instrumental_path=instrumental_wav,
                    ass_path=ass_path,
                    output_mp4_path=final_mp4_path,
                    background_image_path=input_bg_path,
                    original_video_path=input_audio_path,
                    background_mode=bg_mode_param,
                    progress_callback=publish_render_progress,
                )
                shutil.copy2(ass_path, final_ass_path)
            else:
                update_state("processing", "Using rendered video checkpoint", 98)

            pm.check_cancelled()
            save_stage_checkpoint(cache_dir, "video_rendered", "vídeo renderizado", 98)

            # Salvar automaticamente no histórico privado do dono da tarefa.
            history_filename = save_video_to_history(final_mp4_path, orig_name, library_dir)
            public_token = create_public_download(owner_user, history_filename)
            save_result_metadata(output_dir, orig_name, history_filename)
            total_processing_seconds = persist_total_processing_seconds()

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
                telegram_external_url,
                total_processing_seconds,
            )

    except StagePauseRequested as pause:
        elapsed_seconds = persist_total_processing_seconds()
        notify_targets(
            telegram_targets,
            f"⏸ <b>Sal0 Karaokê</b>: <b>{orig_name}</b> foi pausado com segurança após "
            f"<b>{pause.label}</b>. Tempo processado: <b>{format_processing_duration(elapsed_seconds)}</b>.",
        )
        raise
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
    result_meta = {}
    meta_file = os.path.join(output_dir, "result_meta.json")
    if os.path.exists(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8") as file:
                result_meta = json.load(file)
                orig_name = result_meta.get("original_filename", "final")
        except Exception:
            pass
    download_name = karaoke_download_filename(orig_name)
    if result_meta.get("history_filename"):
        download_name = os.path.basename(result_meta["history_filename"])
    if inline:
        return inline_file_response(file_path, "video/mp4", request)
    return attachment_file_response(file_path, download_name, "video/mp4")


@app.get("/api/download-subtitles")
def download_subtitles(
    kind: str = Query("primary"),
    current_user: dict = Depends(get_current_user),
):
    output_dir = get_user_paths(current_user)["output"]
    meta_file = os.path.join(output_dir, "result_meta.json")
    if not os.path.isfile(meta_file):
        raise HTTPException(status_code=404, detail="Nenhuma legenda SRT foi gerada nesta conta.")
    try:
        with open(meta_file, "r", encoding="utf-8") as result_file:
            result_meta = json.load(result_file)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Os metadados da legenda não estão disponíveis.")
    subtitle_fields = {
        "primary": "subtitle_filename",
        "original": "original_subtitle_filename",
        "translated": "translated_subtitle_filename",
    }
    if kind not in subtitle_fields:
        raise HTTPException(status_code=400, detail="Tipo de SRT inválido.")
    subtitle_filename = os.path.basename(result_meta.get(subtitle_fields[kind]) or "")
    subtitle_path = os.path.join(get_user_paths(current_user)["library"], "history", subtitle_filename)
    if not subtitle_filename or not os.path.isfile(subtitle_path):
        if kind == "translated" and result_meta.get("translation_error"):
            raise HTTPException(
                status_code=404,
                detail=f"O SRT original está disponível, mas a tradução falhou: {result_meta['translation_error']}",
            )
        raise HTTPException(status_code=404, detail="A legenda SRT solicitada não foi gerada nesta conta.")
    return attachment_file_response(subtitle_path, subtitle_filename, "application/x-subrip")
