"""Validate user choices before creating files or releasing a review."""
import math
import re
import copy

from reprocess_cache import youtube_identity


def validate_processing_options(**options):
    choices = {
        "whisper_model": ({"large-v3-turbo", "large-v3", "medium", "small", "tiny"}, "Modelo de transcrição inválido."),
        "transcription_preset": ({"karaoke", "continuous", "difficult", "fast"}, "Perfil de leitura da voz inválido."),
        "text_position": ({"bottom", "middle", "top"}, "Posição da legenda inválida."),
        "subtitle_mode": ({"syllable", "word", "line", "phrase"}, "Modo de legenda inválido."),
        "background_mode": ({"original", "image", "color"}, "Tipo de fundo inválido."),
        "transcribe_source": ({"original", "vocals"}, "Fonte de áudio inválida."),
        "lyrics_timing": ({"auto", "acoustic"}, "Modo de sincronização inválido."),
        "lyrics_mode": ({"auto", "manual"}, "Modo de letra inválido."),
    }
    for key, (allowed, message) in choices.items():
        if key in options and options[key] not in allowed:
            raise ValueError(message)
    for key, minimum, maximum, label in (
        ("font_size", 16, 120, "Tamanho da fonte"),
        ("words_per_line", 0, 30, "Palavras por linha"),
        ("max_chars_line", 0, 100, "Caracteres por linha"),
        ("backing_vocals_volume", 0, 100, "Volume dos backing vocals"),
    ):
        if key in options:
            value = options[key]
            if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
                raise ValueError(f"{label} deve estar entre {minimum} e {maximum}.")
    if "text_color" in options and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(options["text_color"])):
        raise ValueError("Escolha uma cor válida para a legenda.")
    url = options.get("youtube_url")
    if url and (not str(url).strip().startswith(('https://', 'http://')) or
                not re.fullmatch(r'[A-Za-z0-9_-]{11}', youtube_identity(str(url).strip()))):
        raise ValueError("Cole o link de um vídeo do YouTube válido.")
    for key in ("library_audio", "library_bg"):
        filename = options.get(key)
        if filename and (str(filename).startswith(".") or "/" in str(filename) or "\\" in str(filename)):
            raise ValueError("Selecione um arquivo válido da Biblioteca.")


def validate_review_segments(segments):
    if not segments:
        raise ValueError("Mantenha pelo menos uma linha de legenda antes de renderizar.")
    previous_start = -1.0
    for index, segment in enumerate(segments, 1):
        if not segment.text.strip():
            raise ValueError(f"Linha {index}: escreva a letra ou exclua a linha vazia.")
        start, end = segment.start, segment.end
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f"Linha {index}: o início deve ser positivo ou zero e o fim deve vir depois do início.")
        if start < previous_start:
            raise ValueError(f"Linha {index}: mantenha os tempos de início em ordem crescente.")
        previous_start = start
        for word in segment.words or []:
            if not math.isfinite(word.start) or not math.isfinite(word.end) or word.start < 0 or word.end < word.start:
                raise ValueError(f"Linha {index}: os tempos das palavras são inválidos. Recarregue a revisão.")


def canonical_review_segments(segments, original_segments):
    from lyrics_sync import anchor_synced_animation
    updated_segments = []
    for segment_index, s in enumerate(segments):
        seg_text = s.text if s.synced_line else s.text.strip()
        if s.synced_line:
            if getattr(s, "acoustic_animation", False):
                source = {"start": s.start, "end": s.end, "text": seg_text}
                acoustic = [{"words": [{"word": w.word, "start": w.start, "end": w.end}
                                        for w in (s.words or [])]}]
                updated_segments.extend(anchor_synced_animation([source], acoustic))
                continue
            updated_segments.append({"start": s.start, "end": s.end, "text": seg_text,
                                     "words": [], "synced_line": True})
            continue
        words_list = seg_text.split()

        orig_words = []
        if s.words:
            orig_words = [{"word": w.word, "start": w.start, "end": w.end} for w in s.words]

        if len(orig_words) == len(words_list):
            orig_dur = s.words[-1].end - s.words[0].start if len(s.words) > 0 else 0
            new_dur = s.end - s.start
            original = original_segments[segment_index] if segment_index < len(original_segments) else {}
            clocks_changed = (s.start != original.get("start") or s.end != original.get("end"))
            if clocks_changed and orig_dur > 0 and new_dur > 0:
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

        original = original_segments[segment_index] if segment_index < len(original_segments) else {}
        original_words = original.get('words', [])
        for index, word in enumerate(words):
            if index < len(original_words):
                prior = original_words[index]
                if (str(word['word']).strip() == str(prior.get('word', '')).strip()
                        and abs(word['start'] - prior.get('start', -1)) < 1e-6
                        and abs(word['end'] - prior.get('end', -1)) < 1e-6):
                    for key in ('alignment_chars', 'alignment_score'):
                        if key in prior:
                            word[key] = copy.deepcopy(prior[key])
            word['lyric_line_id'] = f'review:{segment_index}'
        if words:
            words[0]['lyric_line_start'] = True
            words[-1]['lyric_line_break'] = True

        updated_segments.append({
            "start": s.start,
            "end": s.end,
            "text": seg_text,
            "words": words
        })

    return updated_segments
