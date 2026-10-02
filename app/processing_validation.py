"""Validate user choices before creating files or releasing a review."""
import math
import re

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
