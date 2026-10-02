import os
import logging
import math
import re
import unicodedata

logger = logging.getLogger("karaoke")

AUTO_WORDS_PER_LINE = 9
AUTO_MAX_CHARS_LINE = 54
AUTO_MAX_PHRASE_WORDS = 24
AUTO_MAX_PHRASE_CHARS = 160
AUTO_MAX_PHRASE_DURATION = 14.0

def format_time(seconds: float) -> str:
    """Converte segundos para o formato de tempo do ASS: H:MM:SS.CS (Centisegundos)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    
    # Tratar overflow de arredondamento
    if cs == 100:
        s += 1
        cs = 0
    if s == 60:
        m += 1
        s = 0
    if m == 60:
        h += 1
        m = 0
        
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def html_color_to_ass(hex_color: str) -> str:
    """Converte cores hexadecimais HTML (#RRGGBB) para o formato ASS (&H00BBGGRR)."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) == 6:
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        # ASS usa formato Alpha-Blue-Green-Red (AABBGGRR)
        return f"&H00{b}{g}{r}"
    return "&H0000FFFF" # Amarelo padrão se falhar
def split_and_wrap_segments(
    segments: list[dict],
    words_per_line: int = 0,
    max_chars_line: int = 0,
    break_on_punctuation: bool = True,
) -> list[dict]:
    """Choose sung phrases independently of the visual wrapping preferences.

    Synchronized verses pass through intact. Confirmed lyric markers take
    precedence over ASR chunk boundaries; otherwise punctuation, pauses and
    sentence starts provide boundaries. Safety limits only bound unusually
    long unpunctuated recognition, without leaving a connector behind.
    """
    word_stream, passthrough_segments = [], []
    for segment in segments:
        words = segment.get('words', [])
        if not words or segment.get('synced_line'):
            passthrough_segments.append(dict(segment))
            continue
        for index, word in enumerate(words):
            word_stream.append({'word': word, 'source_end': index == len(words) - 1})

    # These short connectors should stay with the word completing the phrase.
    connectors = set('a o as os um uma uns umas de da do das dos em no na nos nas '
                     'por para pra pro com sem e ou que se me te lhe nos vos '
                     'the a an and or of to for with from at in on my your'.split())
    next_marker, marker = [], None
    for index in range(len(word_stream) - 1, -1, -1):
        if word_stream[index]['word'].get('lyric_line_break'):
            marker = index
        next_marker.append(marker)
    next_marker.reverse()

    chunks, current = [], []
    for index, entry in enumerate(word_stream):
        word = entry['word']
        current.append(word)
        clean = str(word.get('word', '')).strip()
        text = ''.join(str(item.get('word', '')) for item in current).strip()
        count = len(current)
        duration = float(word.get('end', 0)) - float(current[0].get('start', 0))
        following = word_stream[index + 1]['word'] if index + 1 < len(word_stream) else None
        gap = float(following.get('start', 0)) - float(word.get('end', 0)) if following else 0
        next_text = str(following.get('word', '')).strip() if following else ''
        trailing_connector = clean.casefold().strip('.,!?;:') in connectors
        strong_stop = break_on_punctuation and clean.endswith(('.', '?', '!', ';', ':'))
        comma = break_on_punctuation and clean.endswith(',')
        soft_target = count >= AUTO_WORDS_PER_LINE or len(text) >= AUTO_MAX_CHARS_LINE
        # A capitalized ASR continuation alone is not sufficient: also require
        # a pause, a segment boundary, or a substantial sung phrase.
        sentence_start = (next_text[:1].isupper() and next_text != 'I' and count >= 4
                          and (gap >= .12 or entry['source_end'] or soft_target or duration >= 4))
        natural_boundary = (strong_stop and count >= 3) or (
            not trailing_connector and (
                (gap >= .75 and count >= 2)
                or sentence_start
                or (soft_target and (gap >= .30 or comma))
            )
        )
        safety_limit = (count >= AUTO_MAX_PHRASE_WORDS or len(text) >= AUTO_MAX_PHRASE_CHARS
                        or duration >= AUTO_MAX_PHRASE_DURATION)
        guided = next_marker[index] is not None
        should_break = (bool(word.get('lyric_line_break')) or following is None
                        or (not guided and (natural_boundary or (safety_limit and not trailing_connector))))
        if should_break:
            chunks.append(current)
            current = []

    result = [dict(start=chunk[0]['start'], end=chunk[-1]['end'],
                   text=''.join(str(word.get('word', '')) for word in chunk).strip(), words=chunk)
              for chunk in chunks]
    result.extend(passthrough_segments)
    result.sort(key=lambda segment: float(segment.get('start', 0)))
    logger.info('Segmentacao por frases: %s segmentos -> %s versos; quebra visual=%s/%s.',
                len(segments), len(result), words_per_line, max_chars_line)
    return result

def insert_instrumental_breaks(segments: list[dict]) -> list[dict]:
    """
    Insere avisos visuais de 'Instrumental' e contagens regressivas (3, 2, 1)
    quando houver pausas (gaps) maiores ou iguais a 3 segundos entre os versos ou na introdução.
    """
    if not segments:
        return []
        
    new_segments = []
    
    # 1. Tratar a introdução da música se ela for longa (>= 3 segundos)
    first_start = segments[0]["start"]
    if first_start >= 3.0:
        if first_start > 3.0:
            new_segments.append({
                "start": 0.0,
                "end": first_start - 3.0,
                "text": "Instrumental",
                "words": []
            })
        new_segments.append({
            "start": max(0.0, first_start - 3.0),
            "end": max(0.0, first_start - 2.0),
            "text": "Instrumental (3)",
            "words": []
        })
        new_segments.append({
            "start": max(0.0, first_start - 2.0),
            "end": max(0.0, first_start - 1.0),
            "text": "Instrumental (2)",
            "words": []
        })
        new_segments.append({
            "start": max(0.0, first_start - 1.0),
            "end": first_start,
            "text": "Instrumental (1)",
            "words": []
        })
        
    # 2. Tratar os intervalos entre todos os versos
    for idx in range(len(segments)):
        curr_seg = segments[idx]
        new_segments.append(curr_seg)
        
        if idx < len(segments) - 1:
            next_seg = segments[idx + 1]
            gap_duration = next_seg["start"] - curr_seg["end"]
            
            if gap_duration >= 3.0:
                gap_start = curr_seg["end"]
                gap_end = next_seg["start"]
                
                # Inserir o rótulo puramente instrumental se houver espaço
                if gap_duration > 3.0:
                    new_segments.append({
                        "start": gap_start,
                        "end": gap_end - 3.0,
                        "text": "Instrumental",
                        "words": []
                    })
                    
                # Inserir a contagem regressiva nos últimos 3 segundos antes do próximo verso
                new_segments.append({
                    "start": gap_end - 3.0,
                    "end": gap_end - 2.0,
                    "text": "Instrumental (3)",
                    "words": []
                })
                new_segments.append({
                    "start": gap_end - 2.0,
                    "end": gap_end - 1.0,
                    "text": "Instrumental (2)",
                    "words": []
                })
                new_segments.append({
                    "start": gap_end - 1.0,
                    "end": gap_end,
                    "text": "Instrumental (1)",
                    "words": []
                })
                
    return new_segments

def synced_animation_text(segment, normal_color, highlight_color, line_breaks=(), subtitle_mode='syllable'):
    """Keep original text visible; only the selected color animation uses clocks."""
    spans = segment.get('animation_words')
    if not spans and not segment.get('synced_line') and segment.get('words'):
        spans = [dict(word) for word in segment['words']]
        # Whisper often includes a leading space excluded from the displayed line.
        spans[0]['word'] = str(spans[0].get('word', '')).lstrip()
        spans[-1]['word'] = str(spans[-1].get('word', '')).rstrip()
    if subtitle_mode in {'line', 'phrase'} or not spans:
        spans = [{'word': str(segment['text'])}]
    if ''.join(str(span.get('word', '')) for span in spans) != str(segment['text']):
        # An old/stale animation cache can never change the authoritative text.
        spans = [{'word': str(segment['text'])}]
    result = ''
    duration_cs = max(0, round((segment['end'] - segment['start']) * 100))
    offset = 0
    for span in spans:
        tags = f"\\1c{normal_color}\\2c{normal_color}\\k0"
        if 'start' in span and 'end' in span:
            start_cs = min(duration_cs, max(0, round((span['start'] - segment['start']) * 100)))
            end_cs = min(duration_cs, max(start_cs + 1, round((span['end'] - segment['start']) * 100)))
            if end_cs > start_cs:
                # libass >= 0.17 supports an absolute karaoke start (\kt).
                # Pauses need no invisible characters that could shift or wrap text.
                if subtitle_mode == 'word':
                    # Fade the whole word at its real onset, without a hard
                    # color switch or any change to the recognition clocks.
                    fade_end_ms = start_cs * 10 + min(120, (end_cs - start_cs) * 10)
                    tags = (f"\\1c{normal_color}\\2c{normal_color}\\k0"
                            f"\\t({start_cs * 10},{fade_end_ms},\\1c{highlight_color})")
                else:
                    # ASS sweeps from secondary (pending) to primary (sung).
                    tags = f"\\1c{highlight_color}\\2c{normal_color}\\kt{start_cs}\\kf{end_cs - start_cs}"
        word = span['word']
        # Visual wrapping never changes the source text or its timing data.
        for boundary in sorted((b for b in line_breaks if offset <= b < offset + len(word)), reverse=True):
            index = boundary - offset
            word = word[:index] + r'\N' + word[index:]
        result += '{' + tags + '}' + word
        offset += len(span['word'])
    return result


def synced_display_layout(text, font_size, words_per_line=0, max_chars_line=0, height_limit=260):
    """Wrap original words locally and reserve a bounded display region.

    Conservative glyph widths leave room for font substitution. Font reduction
    applies only when the complete provider verse would exceed its own region.
    The result contains display breaks, never new lyric segments or clocks.
    """
    def units(value):
        total = 0.0
        for char in value:
            if unicodedata.combining(char):
                continue
            if char.isspace():
                total += .4
            elif char in 'ilI.,!\'`:;|':
                total += .5
            elif char in 'MW@%' or unicodedata.east_asian_width(char) in 'WF':
                total += 1.2
            elif char.isupper() or not char.isascii():
                total += 1.0
            else:
                total += .8
        return total

    size = max(8, int(font_size))
    words_limit = words_per_line if words_per_line > 0 else AUTO_WORDS_PER_LINE
    chars_limit = max_chars_line if max_chars_line > 0 else AUTO_MAX_CHARS_LINE
    tokens = list(re.finditer(r'\S+\s*', str(text)))
    for _ in range(12):
        breaks, widths = [], []
        width, chars, words = 0.0, 0, 0
        for token in tokens:
            value = token.group()
            token_width = units(value) * size
            if words and (words >= words_limit or chars + len(value.rstrip()) > chars_limit
                          or width + token_width > 1120):
                breaks.append(token.start())
                widths.append(width)
                width, chars, words = 0.0, 0, 0
            width += token_width
            chars += len(value)
            words += 1
        widths.append(width)
        height = len(widths) * size * 1.4 + 8
        fitted = max(8, math.floor(min(size, size * height_limit / height,
                                       size * 1120 / max(1, max(widths)))))
        if fitted == size:
            return {'font_size': size, 'breaks': breaks, 'height': math.ceil(height)}
        size = fitted
    return {'font_size': size, 'breaks': breaks, 'height': math.ceil(height)}


def synced_display_positions(current, preview, text_position, reserve_preview=False):
    """Place lyrics in fixed regions, independent of the current line count."""
    if preview or reserve_preview:
        # Reserve the same space through every verse and every countdown.
        # The active baseline and preview top never jump as the text changes.
        total_height = 260 + 24 + 170
        top = 35 if text_position == 'top' else (
            (720 - total_height) / 2 if text_position == 'middle' else 720 - 35 - total_height)
        active = f"{{\\an2\\pos(640,{round(top + 260)})\\q2\\fs{current['font_size']}}}"
        following = (f"{{\\an8\\pos(640,{round(top + 284)})\\q2\\fs{preview['font_size']}}}"
                     if preview else '')
    else:
        alignment, y = {'top': (8, 35), 'middle': (5, 360), 'bottom': (2, 685)}.get(text_position, (2, 685))
        active = f"{{\\an{alignment}\\pos(640,{y})\\q2\\fs{current['font_size']}}}"
        following = ''
    return active, following

def generate_ass_karaoke(
    segments: list[dict], 
    output_ass_path: str,
    font_size: int = 32,
    text_color_hex: str = "#00FFFF",
    text_position: str = "bottom",
    subtitle_mode: str = "syllable",
    words_per_line: int = 0,
    max_chars_line: int = 40,
    break_on_punctuation: bool = True,
    show_instrumental: bool = True,
    show_next_line_preview: bool = False,
    keep_first_line_visible: bool = False
):
    """
    Gera um arquivo de legenda ASS customizado.
    Suporta os modos de legenda:
    - 'syllable': Segue cada sílaba/palavra com efeito clássico de varredura de cor (\\kf).
    - 'phrase': Exibe as frases/linhas inteiras sincronizadas estaticamente.
    """
    logger.info(f"Gerando legenda ASS ({subtitle_mode}): fonte={font_size}, cor={text_color_hex}, pos={text_position}, show_inst={show_instrumental}, preview={show_next_line_preview}")
    
    # 1. Aplicar quebra de frase e limite de palavras
    segments = split_and_wrap_segments(
        segments=segments,
        words_per_line=words_per_line,
        max_chars_line=max_chars_line,
        break_on_punctuation=break_on_punctuation
    )
    
    # 2. Inserir pausas instrumentais se ativado
    if show_instrumental:
        segments = insert_instrumental_breaks(segments)
    
    # 3. Manter o verso atual visível até a entrada do próximo, sem um vazio artificial.
    for idx in range(len(segments) - 1):
        curr = segments[idx]
        nxt = segments[idx + 1]
        if (not curr.get("synced_line") and "Instrumental" not in nxt["text"]
                and "Instrumental" not in curr["text"]):
            gap = nxt["start"] - curr["end"]
            if gap > 0:
                curr["end"] = nxt["start"]
    
    # 4. Determinar o alinhamento ASS (2 = base centro, 5 = meio centro, 8 = topo centro)
    alignment = 2
    if text_position == "middle":
        alignment = 5
    elif text_position == "top":
        alignment = 8

    # 5. Configurar cores conforme o modo de legenda
    ass_primary_color = "&H00FFFFFF" # Branco por padrão para karaoke
    ass_secondary_color = html_color_to_ass(text_color_hex) # Cor de destaque para karaoke
    
    if subtitle_mode in {"phrase", "line"}:
        # Em modo frase comum, a cor principal é a cor de destaque selecionada
        ass_primary_color = html_color_to_ass(text_color_hex)
        ass_secondary_color = "&H00FFFFFF"

    # Configurar a prévia com contraste legível (alpha 50 no canal principal)
    ass_dimmed_color = html_color_to_ass(text_color_hex).replace("&H00", "&H50")
    if subtitle_mode in {"syllable", "word"}:
        ass_dimmed_color = "&H50FFFFFF" # Prévia branca legível sobre o vídeo

    # Configurar margens verticais para alinhar a linha ativa e a próxima
    margin_v_default = 55
    margin_v_next = 15
    if text_position == "top":
        margin_v_default = 15
        margin_v_next = 55

    # Cabeçalho padrão do ASS com estilos e configurações de tela ajustadas
    ass_header = f"""[Script Info]
; Script generated by Sal0 karaoke
Title: Sal0 Karaoke Legenda
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1280
PlayResY: 720

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},{ass_primary_color},{ass_secondary_color},&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,1,{alignment},20,20,{margin_v_default},1
Style: NextLine,Arial,{int(font_size * 0.85)},{ass_dimmed_color},&H00FFFFFF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,1,{alignment},20,20,{margin_v_next},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [ass_header]
    
    first_lyrics_seg = next((seg for seg in segments if "Instrumental" not in seg['text']), None)
    persistent_intro = bool(keep_first_line_visible and first_lyrics_seg and first_lyrics_seg['start'] > 0)
    intro_preview_layout = None
    instrumental_layout = None
    if persistent_intro:
        if show_instrumental and first_lyrics_seg['start'] >= 3:
            instrumental_layout = synced_display_layout('Instrumental (3)', font_size, words_per_line, max_chars_line)
            intro_preview_layout = synced_display_layout(first_lyrics_seg['text'], int(font_size * .85),
                                                         words_per_line, max_chars_line, height_limit=170)
            _, intro_pos = synced_display_positions(instrumental_layout, intro_preview_layout, text_position)
            intro_layout = intro_preview_layout
        else:
            intro_layout = synced_display_layout(first_lyrics_seg['text'], font_size, words_per_line, max_chars_line)
            intro_pos, _ = synced_display_positions(intro_layout, None, text_position, show_next_line_preview)
        intro_text = synced_animation_text({'text': first_lyrics_seg['text'], 'start': 0, 'end': 1},
                                           ass_primary_color, ass_primary_color, intro_layout['breaks'])
        lines.append(f"Dialogue: 0,{format_time(0)},{format_time(first_lyrics_seg['start'])},Default,,0,0,0,,{intro_pos}{intro_text}\n")

    for idx, seg in enumerate(segments):
        start_time_str = format_time(seg["start"])
        end_time_str = format_time(seg["end"])
        next_seg = segments[idx + 1] if show_next_line_preview and idx + 1 < len(segments) else None
        preview_seg = next_seg if next_seg and 'Instrumental' not in next_seg['text'] else None
        if show_next_line_preview and 'Instrumental' in seg['text']:
            upcoming = next((candidate for candidate in segments[idx + 1:]
                             if 'Instrumental' not in candidate['text']), None)
            if upcoming and seg['start'] >= upcoming['start'] - 3:
                preview_seg = upcoming
        intro_instrumental = bool(persistent_intro and intro_preview_layout and
                                  seg['start'] < first_lyrics_seg['start'])
        if intro_instrumental:
            # One persistent first verse, shared with the entire countdown.
            preview_seg = first_lyrics_seg
        active_layout = synced_display_layout(seg['text'], font_size, words_per_line, max_chars_line)
        preview_layout = (synced_display_layout(preview_seg['text'], int(font_size * .85),
                          words_per_line, max_chars_line, height_limit=170) if preview_seg else None)
        if intro_instrumental:
            active_layout['height'] = instrumental_layout['height']
        active_pos, preview_pos = synced_display_positions(active_layout, preview_layout, text_position,
                                                           show_next_line_preview or intro_instrumental)
        text = synced_animation_text(seg, ass_primary_color, ass_secondary_color,
                                     active_layout['breaks'], subtitle_mode)
        fade = (r'{\fad(80,0)}' if not seg.get('synced_line') and subtitle_mode in {'word', 'syllable'}
                and 'Instrumental' not in seg['text'] else '')
        lines.append(f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{active_pos}{fade}{text}\n")
        if preview_seg and not intro_instrumental:
            preview_text = synced_animation_text({'text': preview_seg['text'], 'start': 0, 'end': 1},
                                                 ass_dimmed_color, ass_dimmed_color,
                                                 preview_layout['breaks'])
            lines.append(f"Dialogue: 0,{start_time_str},{end_time_str},NextLine,,0,0,0,,{preview_pos}{preview_text}\n")

    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    logger.info("Legenda ASS gerada com sucesso.")
