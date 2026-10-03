"""A draft belongs to one media source; queued jobs keep their own text copy."""
import hashlib
import json
import os
import tempfile


def draft_path(folder, source_key):
    source_key = str(source_key or "legacy")
    if len(source_key) > 512:
        raise ValueError("A identificação da mídia é muito longa.")
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
    return os.path.join(folder, "lyrics-drafts", digest + ".json")


def read_draft(folder, source_key):
    try:
        with open(draft_path(folder, source_key), encoding="utf-8") as file:
            data = json.load(file)
        return {"source_key": str(source_key or "legacy"), "lyrics_text": str(data.get("lyrics_text") or ""),
                "lyrics_mode": "manual" if data.get("lyrics_mode") == "manual" else "auto"}
    except (OSError, ValueError, TypeError):
        return {"source_key": str(source_key or "legacy"), "lyrics_text": "", "lyrics_mode": "auto"}


def write_draft(folder, source_key, text, mode="manual"):
    path = draft_path(folder, source_key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".draft-", dir=os.path.dirname(path))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump({"lyrics_text": text or "", "lyrics_mode": mode}, file, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def clear_draft(folder, source_key):
    # Keep an empty manual draft so switching back does not silently fetch another guide.
    write_draft(folder, source_key, "", "manual")
