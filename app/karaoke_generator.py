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
    """
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

def generate_ass_karaoke(
    segments: list[dict], 
    output_ass_path: str,
    font_size: int = 32,
    text_color_hex: str = "#00FFFF",
    text_position: str = "bottom",
    subtitle_mode: str = "syllable",
    words_per_line: int = 0,
    max_chars_line: int = 40,
    break_on_punctuation: bool = True
):
    """
    Gera um arquivo de legenda ASS customizado.
    Suporta os modos de legenda:
    - 'syllable': Segue cada sílaba/palavra com efeito clássico de varredura de cor (\kf).
    - 'phrase': Exibe as frases/linhas inteiras sincronizadas estaticamente.
    """
    logger.info(f"Gerando legenda ASS customizada ({subtitle_mode}): fonte={font_size}, cor={text_color_hex}, pos={text_position}, max_words={words_per_line}, max_chars={max_chars_line}, break_punct={break_on_punctuation}")
    
    # 1. Aplicar quebra de frase e limite de palavras
    segments = split_and_wrap_segments(
        segments=segments,
        words_per_line=words_per_line,
        max_chars_line=max_chars_line,
        break_on_punctuation=break_on_punctuation
    )
    
    # 2. Determinar o alinhamento ASS (2 = base centro, 5 = meio centro, 8 = topo centro)
    alignment = 2
    if text_position == "middle":
        alignment = 5
    elif text_position == "top":
        alignment = 8

    # 3. Configurar cores conforme o modo de legenda
    ass_primary_color = "&H00FFFFFF" # Branco por padrão para karaoke
    ass_secondary_color = html_color_to_ass(text_color_hex) # Cor de destaque para karaoke
    
    if subtitle_mode == "phrase":
        # Em modo frase comum, a cor principal é a cor de destaque selecionada
        ass_primary_color = html_color_to_ass(text_color_hex)
        ass_secondary_color = "&H00FFFFFF"
    
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
Style: Default,Arial,{font_size},{ass_primary_color},{ass_secondary_color},&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,3,1,{alignment},20,20,50,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [ass_header]
    
    for seg in segments:
        start_time_str = format_time(seg["start"])
        end_time_str = format_time(seg["end"])
        
        if subtitle_mode == "phrase":
            # Legenda comum, sem tags de karaoke
            line = f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{seg['text']}\n"
        else:
            # Modo Karaoke (segue sílabas)
            karaoke_text = ""
            current_ref = seg["start"]
            
            for word_info in seg["words"]:
                word_text = word_info["word"]
                w_start = word_info["start"]
                w_end = word_info["end"]
                
                # 1. Tratar silêncios intermediários/iniciais (gaps)
                if w_start > current_ref:
                    gap_dur = w_start - current_ref
                    gap_cs = int(round(gap_dur * 100))
                    if gap_cs > 0:
                        karaoke_text += f"{{\\kf{gap_cs}}}"
                    current_ref = w_start
                    
                # 2. Calcular a duração da palavra (mínimo de 5 centisegundos para segurança)
                word_dur = w_end - w_start
                if word_dur <= 0:
                    word_dur = 0.05
                word_cs = int(round(word_dur * 100))
                
                # 3. Separar espaços laterais
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
                
            # 4. Tratar silêncio final
            if seg["end"] > current_ref:
                trail_dur = seg["end"] - current_ref
                trail_cs = int(round(trail_dur * 100))
                if trail_cs > 0:
                    karaoke_text += f"{{\\kf{trail_cs}}}"
                    
            line = f"Dialogue: 0,{start_time_str},{end_time_str},Default,,0,0,0,,{karaoke_text}\n"
            
        lines.append(line)
        
    with open(output_ass_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
        
    logger.info("Legenda ASS gerada com sucesso.")
