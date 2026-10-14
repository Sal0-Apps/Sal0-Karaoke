"""Retain one editable queue per owner until a fresh source starts the next queue."""
import json
import os
import re
import shutil
import tempfile
from functools import lru_cache

from reprocess_cache import copy_reusable_inputs

ACTIVE = {"queued", "processing"}
STATUSES = ACTIVE | {"done", "error", "cancelled", "removed", "replaced"}
SEGMENT_FILES = ("review_draft.json", "reviewed_segments.json", "subtitle_segments_original.json", "lyrics_guide_cache.json",
                 "transcribed_segments.json", "synced_acoustic_segments.json")


def display_order(jobs):
    """Show live work first while preserving the worker's pending order."""
    priority = {"processing": 0, "queued": 1}
    return sorted(jobs, key=lambda job: priority.get(job.get("status"), 2))


def plan_enqueue(jobs, job):
    """Plan on copies: a failed queue write must not discard the previous batch."""
    jobs = [dict(item) for item in jobs]
    job = dict(job)
    owned = [item for item in jobs if item.get("owner_username") == job.get("owner_username")]
    source_id = job.get("cache_source_id")
    source = next((item for item in owned if item.get("id") == source_id), None)
    retired = []
    if source_id and source_id != "legacy":
        if not source:
            raise ValueError("Essa execução não está mais no cache da fila.")
        if source.get("status") == "processing":
            raise ValueError("Aguarde essa execução terminar antes de refazê-la.")
        job["batch_id"] = source.get("batch_id") or source["id"]
        job["revision_of"] = source["id"]
    elif any(item.get("status") in ACTIVE for item in owned):
        job["batch_id"] = next(item.get("batch_id") or item["id"] for item in owned
                               if item.get("status") in ACTIVE)
    else:
        retired = owned
        jobs = [item for item in jobs if item.get("owner_username") != job.get("owner_username")]
        job["batch_id"] = job["id"]
    if source and source.get("status") == "queued":
        position = jobs.index(source)
        source["status"] = "replaced"
        source["message"] = "Substituída por uma nova execução na mesma fila."
        jobs.insert(position + 1, job)
    else:
        jobs.append(job)
    return jobs, retired


def read_json(path, fallback=None):
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError):
        return fallback


def read_segments(cache_dir):
    for name in SEGMENT_FILES:
        segments = read_json(os.path.join(cache_dir, name))
        if isinstance(segments, dict):
            segments = segments.get("segments")
        if isinstance(segments, list) and segments:
            return segments
    return []


def has_segments(cache_dir):
    """The queue needs availability, not the complete transcription of every item."""
    for name in SEGMENT_FILES:
        try:
            with open(os.path.join(cache_dir, name), encoding="utf-8") as file:
                head = file.read(128).lstrip()
            if head.startswith("[") and head[1:].lstrip().startswith("{"):
                return True
            if name == "lyrics_guide_cache.json" and re.search(r'"segments"\s*:\s*\[\s*\{', head):
                return True
        except (OSError, UnicodeError):
            pass
    return False


@lru_cache(maxsize=256)
def _probe_video(path, size, modified_ns, probe):
    return bool(probe(path))


def has_video(path, probe):
    """Probe each unchanged preview source once, shared by info and media requests."""
    try:
        info = os.stat(path)
    except (OSError, TypeError):
        return False
    return _probe_video(path, info.st_size, info.st_mtime_ns, probe)


def read_draft(cache_dir):
    draft = read_json(os.path.join(cache_dir, "review_draft.json"))
    return draft if isinstance(draft, list) and draft else None


def write_draft(cache_dir, segments):
    handle, temporary = tempfile.mkstemp(prefix=".review-", dir=cache_dir)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(segments, file, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, os.path.join(cache_dir, "review_draft.json"))
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def copy_revision_cache(source, destination):
    copy_reusable_inputs(source, destination)
    for name in os.listdir(source):
        if name in {"reviewed_segments.json", "review_draft.json"} or name.startswith("subtitle_background."):
            if os.path.isfile(os.path.join(source, name)):
                shutil.copy2(os.path.join(source, name), os.path.join(destination, name))
    # A new execution must render new output. It may resume compatible expensive inputs.
    checkpoints = read_json(os.path.join(source, "stage_checkpoints.json"), {})
    stages = checkpoints.get("completed_stages", {})
    if not read_draft(destination):
        review_name = "reviewed_segments.json" if "transcription_reviewed" in stages else (
            "subtitle_segments_original.json" if "subtitle_transcription_reviewed" in stages else None)
        review = read_json(os.path.join(source, review_name)) if review_name else None
        if isinstance(review, list) and review:
            write_draft(destination, review)
    checkpoints = {"active_processing_seconds": 0, "completed_stages": {
        key: value for key, value in stages.items()
        if key in {"input_ready", "audio_extracted", "vocals_separated", "transcription_ready", "transcription_reviewed",
                   "subtitle_audio_ready", "subtitle_transcription_ready", "subtitle_transcription_reviewed"}}}
    with open(os.path.join(destination, "stage_checkpoints.json"), "w", encoding="utf-8") as file:
        json.dump(checkpoints, file, ensure_ascii=False, indent=2)


def public_options(job):
    pipeline = job.get("pipeline") or {}
    excluded = {"input_audio_path", "input_bg_path", "owner_user", "cache_dir", "output_dir", "library_dir",
                "subtitle_background_path", "app_base_url", "youtube_publish_options", "youtube_url"}
    result = {key: value for key, value in pipeline.items() if key not in excluded}
    saved = job.get("creation_options") or {}
    result.update(save_to_library=saved.get("save_to_library", True),
                  pause_for_editing=saved.get("pause_for_editing", False))
    meta = read_json(os.path.join(pipeline.get("cache_dir", ""), "cache_meta.json"), {})
    result["audio_filename"] = meta.get("audio_filename", job.get("title", ""))
    result["background_filename"] = meta.get("bg_filename", "")
    result["lyrics_text"] = meta.get("lyrics_text", result.get("lyrics_text", "")) or ""
    result["lyrics_mode"] = "manual"
    result["lyrics_selected"] = True
    result["easy_mode"] = job.get("process_summary", {}).get("mode") == "Modo Rápido"
    publication = pipeline.get("youtube_publish_options") or {}
    result.update(youtube_publish=bool(publication), youtube_playlist_id=publication.get("playlist_id", ""),
                  youtube_title=publication.get("title_override", ""),
                  youtube_extra_playlists=bool(publication.get("additional_playlists")),
                  youtube_additional_playlists=json.dumps(publication.get("additional_playlists") or []))
    return result
