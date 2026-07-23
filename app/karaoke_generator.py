import os
import logging

logger = logging.getLogger("karaoke")

AUTO_WORDS_PER_LINE = 9
AUTO_MAX_CHARS_LINE = 54
AUTO_HARD_WORDS_PER_LINE = 15
AUTO_HARD_CHARS_LINE = 86
AUTO_MAX_LINE_DURATION = 10.0

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
    """Cria versos legiveis sem usar os cortes internos do Whisper como regra.

    A letra oficial, quando encontrada, fornece marcadores de fim de verso. Sem
    ela, pontuacao, pausas e os limites suaves guiam a divisao. Um limite duro
    continua protegendo a tela contra blocos excessivamente grandes.
    """
    soft_words = words_per_line if words_per_line > 0 else AUTO_WORDS_PER_LINE
    soft_chars = max_chars_line if max_chars_line > 0 else AUTO_MAX_CHARS_LINE
    hard_words = words_per_line if words_per_line > 0 else AUTO_HARD_WORDS_PER_LINE
    hard_chars = max_chars_line if max_chars_line > 0 else AUTO_HARD_CHARS_LINE
    word_stream = []
    passthrough_segments = []

    for segment_index, segment in enumerate(segments):
        words = segment.get("words", [])
        if not words:
            passthrough_segments.append(segment)
            continue
        for word_index, word_info in enumerate(words):
            word_stream.append({
                "word": word_info,
                "source_end": word_index == len(words) - 1,
                "source_segment": segment_index,
            })

    chunks = []
    current_chunk = []
    for index, entry in enumerate(word_stream):
        word_info = entry["word"]
        current_chunk.append(word_info)
        clean_text = str(word_info.get("word", "")).strip()
        chunk_text = "".join(str(word.get("word", "")) for word in current_chunk).strip()
        word_count = len(current_chunk)
        char_count = len(chunk_text)
        duration = float(word_info.get("end", 0)) - float(current_chunk[0].get("start", 0))

        next_entry = word_stream[index + 1] if index + 1 < len(word_stream) else None
        next_word = next_entry["word"] if next_entry else None
        gap = (
            float(next_word.get("start", 0)) - float(word_info.get("end", 0))
            if next_word else 0.0
        )
        official_line_end = bool(word_info.get("lyric_line_break"))
        strong_punctuation = bool(clean_text and clean_text[-1] in ".?!;:")
        soft_punctuation = bool(clean_text and clean_text[-1] == ",")
        reached_soft_target = word_count >= soft_words or char_count >= soft_chars
        reached_hard_limit = (
            word_count >= hard_words
            or char_count >= hard_chars
            or duration >= AUTO_MAX_LINE_DURATION
        )
        natural_soft_boundary = (
            (break_on_punctuation and soft_punctuation and word_count >= 5)
            or gap >= 0.30
            or entry["source_end"]
        )
        should_break = (
            official_line_end
            or (break_on_punctuation and strong_punctuation and word_count >= 3)
            or (gap >= 0.75 and word_count >= 2)
            or (reached_soft_target and natural_soft_boundary)
            or reached_hard_limit
            or next_entry is None
        )

        if should_break:
            chunks.append(current_chunk)
            current_chunk = []

    new_segments = [
        {
            "start": chunk[0]["start"],
            "end": chunk[-1]["end"],
            "text": "".join(str(word.get("word", "")) for word in chunk).strip(),
            "words": chunk,
        }
        for chunk in chunks
    ]
    new_segments.extend(passthrough_segments)
    new_segments.sort(key=lambda item: float(item.get("start", 0)))
    logger.info(
        "Segmentacao inteligente: %s segmentos -> %s versos; alvos=%s/%s, protecao=%s/%s.",
        len(segments),
        len(new_segments),
        soft_words,
        soft_chars,
        hard_words,
        hard_chars,
    )
    return new_segments


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
        if "Instrumental" not in nxt["text"] and "Instrumental" not in curr["text"]:
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
    
    if subtitle_mode == "phrase":
        # Em modo frase comum, a cor principal é a cor de destaque selecionada
        ass_primary_color = html_color_to_ass(text_color_hex)
        ass_secondary_color = "&H00FFFFFF"

    # Configurar cor ofuscada da próxima linha (transparência alpha 80 no canal principal)
    ass_dimmed_color = html_color_to_ass(text_color_hex).replace("&H00", "&H80")
    if subtitle_mode == "syllable":
        ass_dimmed_color = "&H80FFFFFF" # Branco com 50% de transparência para karaoke

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
    
    # Se configurado para manter a primeira linha visível desde o início do vídeo sem coloração (para introdução)
    if keep_first_line_visible and segments:
        first_lyrics_seg = None
        for seg in segments:
            if "Instrumental" not in seg["text"]:
                first_lyrics_seg = seg
                break
        if first_lyrics_seg and first_lyrics_seg["start"] > 0.0:
            start_str = format_time(0.0)
            end_str = format_time(first_lyrics_seg["start"])
            clean_text = first_lyrics_seg["text"]
            lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{clean_text}\n")
            
    for idx, seg in enumerate(segments):
        start_time_str = format_time(seg["start"])
        end_time_str = format_time(seg["end"])

        # 1. Linha ativa (Default)
        if subtitle_mode in {"phrase", "line"} or not seg.get("words"):
            line = f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{seg['text']}\n"
        else:
            # Modo Karaoke (segue sílabas)
            karaoke_text = ""
            current_ref_cs = 0

            for word_info in seg["words"]:
                word_text = word_info["word"]
                w_start = word_info["start"]
                w_end = word_info["end"]
                word_start_cs = max(0, int(round((w_start - seg["start"]) * 100)))
                word_end_cs = max(word_start_cs + 1, int(round((w_end - seg["start"]) * 100)))

                # O tempo é calculado a partir do início absoluto da linha. Isso
                # evita que arredondamentos de cada palavra se acumulem. Espaços
                # invisíveis consomem pausas reais; uma tag sem texto seria
                # ignorada pelo renderizador ASS e adiantaria as palavras seguintes.
                gap_cs = word_start_cs - current_ref_cs
                if gap_cs > 0:
                    karaoke_text += f"{{\\k{gap_cs}\\alpha&HFF&}}\\h{{\\alpha&H00&}}"

                # Calcular a duração da palavra
                word_cs = max(1, word_end_cs - word_start_cs)

                # Separar espaços
                leading_spaces = len(word_text) - len(word_text.lstrip(' '))
                trailing_spaces = len(word_text.lstrip(' ')) - len(word_text.strip(' '))
                clean_text = word_text.strip(' ')
                
                if clean_text:
                    spaces_before = " " * leading_spaces
                    spaces_after = " " * trailing_spaces
                    karaoke_text += f"{spaces_before}{{\\kf{word_cs}}}{clean_text}{spaces_after}"
                else:
                    karaoke_text += f"{{\\kf{word_cs}}}{word_text}"

                current_ref_cs = word_end_cs

            line = f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{karaoke_text}\n"
            
        lines.append(line)
        
        # 2. Pré-visualização da próxima linha (NextLine - Ofuscada)
        if show_next_line_preview and idx < len(segments) - 1:
            next_seg = segments[idx + 1]
            # Apenas exibe a próxima linha se ela for uma linha de letra (ignora instrumental e contagens)
            if "Instrumental" not in next_seg["text"]:
                preview_line = f"Dialogue: 0,{start_time_str},{end_time_str},NextLine,,0,0,0,,{next_seg['text']}\n"
                lines.append(preview_line)
        
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    logger.info("Legenda ASS gerada com sucesso.")
