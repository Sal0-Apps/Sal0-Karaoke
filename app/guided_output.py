"""Final guide/voice contract, after every cache and human-review path."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


def _read_object(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def finalize_guided_output(audio_path, segments, lyrics, cache_dir, context=None,
                           progress=None, cancel=None):
    from lyric_guide import GUIDE_POLICY_VERSION, enforce_guide_text, prepare_lyrics_guide
    guide = prepare_lyrics_guide(lyrics)
    if not guide:
        return segments, {}
    from lyric_alignment import validate_display_evidence
    checked, evidence_report = validate_display_evidence(audio_path, segments, lyrics, cache_dir,
        context=context, progress=progress, cancel=cancel)
    # A second, pure-text postcondition also covers an unexpected backend fallback.
    verified = checked
    checked, text_report = enforce_guide_text(lyrics, checked)
    if cancel:
        cancel()
    info = os.stat(audio_path)
    identity = dict(policy=GUIDE_POLICY_VERSION, guide=guide, segments=checked,
                    voice_regions=evidence_report.get('voice_regions'),
                    source=dict(path=str(Path(audio_path).resolve()), size=info.st_size, mtime=info.st_mtime_ns))
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                           allow_nan=False).encode()).hexdigest()
    root = Path(cache_dir)
    manifest = root / 'guided_output.json'
    previous = _read_object(manifest)
    # An idempotent postcondition must not erase the acoustic pass's omissions.
    contract = evidence_report.get('guide_contract') if checked == verified else None
    report = {**evidence_report, 'guide_contract': contract or text_report,
              'final_postcondition': text_report, 'strict_signature': signature}
    if previous.get('signature') != signature:
        checkpoint = root / 'stage_checkpoints.json'
        saved = _read_object(checkpoint)
        if not isinstance(saved.get('completed_stages'), dict):
            saved['completed_stages'] = {}
        for stage in ('subtitles_generated', 'video_rendered'):
            saved['completed_stages'].pop(stage, None)
        _save(checkpoint, saved)
    # These are derived files. Reviewed drafts and raw Whisper output stay intact.
    _save(root / 'display_segments.json', checked)
    _save(manifest, dict(signature=signature, segments=checked, report=report))
    if not checked:
        raise ValueError('Nenhum trecho da letra-guia foi confirmado na voz. Confira a guia e a gravação; nenhum texto diferente será usado como alternativa.')
    return checked, report
