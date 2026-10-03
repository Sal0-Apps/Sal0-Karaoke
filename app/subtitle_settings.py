"""Server defaults for speech subtitles, independent of karaoke defaults."""
import json
import os
import re
import tempfile


def normalize_subtitle_settings(data=None):
    data = data or {}
    settings = {
        "text_color": "#FFFFFF", "box_color": "#000000", "box_opacity": 65,
        "font_size": 24, "text_position": "bottom", "video_subtitle_source": "translated",
        "background_color": "#101827", "background_file": "", "background_owner": "",
    }
    for key in ("text_color", "box_color", "background_color"):
        value = str(data.get(key, settings[key]))
        if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            settings[key] = value.upper()
    for key, low, high in (("font_size", 12, 72), ("box_opacity", 0, 100)):
        try:
            settings[key] = max(low, min(high, int(data.get(key, settings[key]))))
        except (TypeError, ValueError):
            pass
    if data.get("text_position") in {"top", "middle", "bottom"}:
        settings["text_position"] = data["text_position"]
    if data.get("video_subtitle_source") in {"translated", "original"}:
        settings["video_subtitle_source"] = data["video_subtitle_source"]
    filename = str(data.get("background_file") or "")
    if filename and filename == os.path.basename(filename) and not filename.startswith(".") and "\\" not in filename:
        settings["background_file"] = filename
    settings["background_owner"] = str(data.get("background_owner") or "")
    return settings


def load_subtitle_settings(path):
    try:
        with open(path, encoding="utf-8") as file:
            return normalize_subtitle_settings(json.load(file))
    except (OSError, ValueError, TypeError):
        return normalize_subtitle_settings()


def save_subtitle_settings(path, data):
    settings = normalize_subtitle_settings(data)
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".subtitle-settings-", dir=folder)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(settings, file, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    return settings
