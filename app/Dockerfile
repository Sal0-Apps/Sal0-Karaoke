FROM python:3.12-slim

# Evitar gravação de arquivos pyc e bufferizar saída
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV NUMBA_CACHE_DIR=/tmp/numba_cache

# Instalar FFmpeg, libsndfile e dependências essenciais
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar e instalar requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --upgrade yt-dlp

# Copiar script auxiliar e pré-baixar os modelos (Whisper Medium e Demucs htdemucs)
COPY download_models.py .
RUN python download_models.py && rm download_models.py

# Copiar código-fonte da aplicação
COPY . .

# Criar os diretórios de upload e saída que serão mapeados
RUN mkdir -p /data/input /data/output

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
