import gc
import logging
from faster_whisper import WhisperModel

logger = logging.getLogger("karaoke")

def transcribe_vocals(vocals_path: str, model_size: str = "medium") -> list[dict]:
    """
    Transcreve a faixa de vocais usando o Whisper selecionado.
    Retorna uma lista de segmentos estruturados contendo palavras e timestamps.
    """
    try:
        # Inicializar o modelo Whisper selecionado na CPU de forma otimizada para RAM
        model = WhisperModel(
            model_size, 
            device="cpu", 
            compute_type="int8",             # Reduz uso de RAM pela metade
            cpu_threads=3,                   # Mantém 1 núcleo livre para o FastAPI responder à web sem lentidão
            download_root="/data/output/models/whisper",
            local_files_only=True            # Não baixa arquivos durante a criação do karaoke
        )
    except Exception as ex:
        logger.error(f"Erro ao carregar o modelo Whisper {model_size}: {ex}")
        raise RuntimeError(
            f"O modelo Whisper '{model_size}' não está baixado no servidor. "
            "Por favor, acesse o painel 'Configurações Avançadas' -> 'Gerenciador de Modelos de IA' e baixe o modelo antes de prosseguir."
        )
    
    logger.info(f"Iniciando transcrição de vocais para o arquivo: {vocals_path}")
    
    # Executar transcrição com timestamps em nível de palavra
    segments, info = model.transcribe(
        vocals_path,
        word_timestamps=True,
        beam_size=5
    )
    
    logger.info(
        f"Idioma detectado: {info.language} "
        f"(Probabilidade: {info.language_probability:.2%})"
    )
    
    structured_segments = []
    
    # Consumir o gerador lazy para extrair os dados e estruturá-los em dicionários
    for segment in segments:
        segment_words = []
        if segment.words:
            for word in segment.words:
                segment_words.append({
                    "word": word.word,
                    "start": word.start,
                    "end": word.end
                })
        
        # Só adiciona o segmento se contiver palavras e texto válido
        if segment_words:
            structured_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
                "words": segment_words
            })
            
    logger.info(
        f"Transcrição concluída. Total de segmentos processados: {len(structured_segments)}"
    )
    
    # Desalocar o modelo da memória de forma agressiva
    logger.info("Desalocando modelo Whisper Medium da memória...")
    del model
    gc.collect()
    logger.info("Memória do Whisper liberada.")
    
    return structured_segments
