"""Shared discovery of usable CTranslate2 Whisper models, without loading weights."""
import json
import logging
import os
from pathlib import Path
import re

logger = logging.getLogger("karaoke")

MODEL_REPOSITORIES = {
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v2": "Systran/faster-whisper-large-v2",
    "medium": "Systran/faster-whisper-medium",
    "small": "Systran/faster-whisper-small",
    "base": "Systran/faster-whisper-base",
    "tiny": "Systran/faster-whisper-tiny",
}
MINIMUM_MODEL_BYTES = {"tiny": 30 * 1024**2, "base": 60 * 1024**2,
                       "small": 150 * 1024**2}


def model_key(model_size):
    key = str(model_size).strip().lower()
    return "large-v3-turbo" if key == "turbo" else key


def resolve_whisper_repo(model_size):
    return MODEL_REPOSITORIES.get(model_key(model_size), model_size)


def _matches(name, key):
    name = name.lower()
    if key == "large-v3-turbo":
        return "turbo" in name
    if key == "large-v3" and "turbo" in name:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", name) is not None


def _usable(directory, key):
    """A PyTorch checkpoint cannot be opened directly by Faster-Whisper."""
    try:
        binary = directory / "model.bin"
        if not binary.is_file() or binary.stat().st_size < MINIMUM_MODEL_BYTES.get(key, 300 * 1024**2):
            return False
        with (directory / "config.json").open(encoding="utf-8") as source:
            return isinstance(json.load(source), dict)
    except (OSError, ValueError):
        return False


def get_model_local_dir(model_size, search_roots=None):
    key = model_key(model_size)
    roots = search_roots if search_roots is not None else (
        "/data/output/models/whisper", "/root/.cache/huggingface/hub",
        os.path.expanduser("~/.cache/huggingface/hub"),
    )
    visited = set()
    for location in roots:
        root = Path(location)
        identity = os.path.normcase(os.path.abspath(root))
        if identity in visited:
            continue
        visited.add(identity)
        try:
            candidates = [root] if _matches(root.name, key) else []
            candidates.extend(entry for entry in root.iterdir() if entry.is_dir() and _matches(entry.name, key))
            for candidate in candidates:
                for directory, children, files in os.walk(candidate):
                    # Hugging Face blobs and partial downloads are not snapshots.
                    children[:] = [name for name in children if name not in {"blobs", ".locks"}]
                    if "model.bin" in files and "config.json" in files and _usable(Path(directory), key):
                        return str(directory)
        except FileNotFoundError:
            continue
        except OSError as error:
            logger.debug("Não foi possível consultar modelos em %s: %s", root, error)
    return None
