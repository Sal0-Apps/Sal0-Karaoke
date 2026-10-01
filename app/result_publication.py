"""Persistent result provenance: only generated karaoke videos may be published."""
import json
import os
import uuid
from pathlib import Path


def record_result_kind(video, kind):
    if kind not in {"karaoke", "subtitle_video"}:
        raise ValueError("Tipo de resultado inválido.")
    video = Path(video)
    folder = video.parent / ".sal0-results"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / (video.name + ".json")
    temporary = folder / (uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps({"filename": video.name, "kind": kind}), encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def result_kind(video):
    video = Path(video)
    if video.suffix.lower() == ".srt":
        return "subtitles"
    if video.suffix.lower() != ".mp4":
        return "unknown"
    marker = video.parent / ".sal0-results" / (video.name + ".json")
    try:
        if marker.exists():
            saved = json.loads(marker.read_text(encoding="utf-8"))
            if saved.get("filename") == video.name and saved.get("kind") in {"karaoke", "subtitle_video"}:
                return saved["kind"]
            return "unknown"
        # Older installations retain provenance for their latest result.
        if video.parent.name == "history":
            metadata = video.parent.parent.parent / "output" / "result_meta.json"
            saved = json.loads(metadata.read_text(encoding="utf-8"))
            if saved.get("history_filename") == video.name:
                if saved.get("result_kind") in {"subtitle_video", "subtitles"}:
                    return "subtitle_video"
                if saved.get("result_kind") in {None, "karaoke"} and not saved.get("original_subtitle_filename"):
                    return "karaoke"
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return "unknown"


def youtube_eligible(video):
    return result_kind(video) == "karaoke"
