import os
import logging

logger = logging.getLogger("karaoke")

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
    max_chars_line: int = 40,
    break_on_punctuation: bool = True
) -> list[dict]:
    r"""
    Divide os segmentos de transcrição em partes menores com base nas restrições de:
    - Quantidade máxima de palavras por linha (words_per_line)
    - Limite de caracteres por linha (max_chars_line)
    - Quebra de frase por pontuação (vírgula, ponto final, exclamação, etc)
    """
    new_segments = []
    
    for seg in segments:
        words = seg.get("words", [])
        if not words:
            new_segments.append(seg)
            continue
            
        current_chunk = []
        current_words_count = 0
        current_chars_count = 0
        chunks = []
        
        for i, w_info in enumerate(words):
            word_text = w_info["word"]
            clean_word = word_text.strip()
            
            current_chunk.append(w_info)
            current_words_count += 1
            current_chars_count += len(word_text)
            
            should_break = False
            
            # 1. Limite de palavras
            if words_per_line > 0 and current_words_count >= words_per_line:
                should_break = True
                
            # 2. Limite de caracteres
            if max_chars_line > 0 and current_chars_count >= max_chars_line:
                should_break = True
                
            # 3. Quebra em pontuações (vírgula, ponto, interrogação, etc.)
            if break_on_punctuation and i < len(words) - 1:
                if clean_word and clean_word[-1] in (',', '.', '?', '!', ';', ':', '(', ')'):
                    should_break = True
            
            # 4. Quebra por silêncio/pausa maior entre palavras (ex: pausa de voz > 0.5s)
            if i < len(words) - 1:
                next_w = words[i+1]
                gap = next_w["start"] - w_info["end"]
                if gap >= 0.5:
                    should_break = True
                    
            if should_break and i < len(words) - 1:
                chunks.append(current_chunk)
                current_chunk = []
                current_words_count = 0
                current_chars_count = 0
                
        if current_chunk:
            chunks.append(current_chunk)
            
        for chunk in chunks:
            chunk_text = "".join([w["word"] for w in chunk]).strip()
            chunk_start = chunk[0]["start"]
            chunk_end = chunk[-1]["end"]
            
            new_segments.append({
                "start": chunk_start,
                "end": chunk_end,
                "text": chunk_text,
                "words": chunk
            })
            
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
    
    # 3. Estender a exibição dos versos até 0.3 segundos antes do início do próximo (se não for instrumental)
    for idx in range(len(segments) - 1):
        curr = segments[idx]
        nxt = segments[idx + 1]
        if "Instrumental" not in nxt["text"] and "Instrumental" not in curr["text"]:
            gap = nxt["start"] - curr["end"]
            if gap > 0.3:
                curr["end"] = nxt["start"] - 0.3
    
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
        if subtitle_mode == "phrase" or not seg.get("words"):
            line = f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{seg['text']}\n"
        else:
            # Modo Karaoke (segue sílabas)
            karaoke_text = ""
            current_ref = seg["start"]
            
            for word_info in seg["words"]:
                word_text = word_info["word"]
                w_start = word_info["start"]
                w_end = word_info["end"]
                
                # Tratar silêncios intermediários (gaps)
                if w_start > current_ref:
                    gap_dur = w_start - current_ref
                    gap_cs = int(round(gap_dur * 100))
                    if gap_cs > 0:
                        karaoke_text += f"{{\\kf{gap_cs}}}"
                    current_ref = w_start
                    
                # Calcular a duração da palavra
                word_dur = w_end - w_start
                if word_dur <= 0:
                    word_dur = 0.05
                word_cs = int(round(word_dur * 100))
                
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
                    
                current_ref = w_end
                
            # Tratar silêncio final
            if seg["end"] > current_ref:
                trail_dur = seg["end"] - current_ref
                trail_cs = int(round(trail_dur * 100))
                if trail_cs > 0:
                    karaoke_text += f"{{\\kf{trail_cs}}}"
                    
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
