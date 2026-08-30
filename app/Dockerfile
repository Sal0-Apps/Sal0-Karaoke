FROM python:3.12-slim

LABEL org.opencontainers.image.title="Sal0 Karaokê" \
      org.opencontainers.image.description="Servidor auto-hospedado para criação local de karaokê e legendas" \
      org.opencontainers.image.version="9.0.2" \
      org.opencontainers.image.source="https://github.com/Sal0-Apps/Sal0-Karaoke" \
      org.opencontainers.image.licenses="MIT"

# Evitar gravação de arquivos pyc e bufferizar saída
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV NUMBA_CACHE_DIR=/tmp/numba_cache

# Instalar FFmpeg, libsndfile, certificados e o runtime JavaScript exigido pelo YouTube
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    ca-certificates \
    curl \
    unzip \
    && architecture="$(dpkg --print-architecture)" \
    && case "$architecture" in \
        amd64) deno_target="x86_64-unknown-linux-gnu" ;; \
        arm64) deno_target="aarch64-unknown-linux-gnu" ;; \
        *) echo "Arquitetura sem pacote Deno disponível: $architecture" >&2; exit 1 ;; \
    esac \
    && curl -fsSL "https://github.com/denoland/deno/releases/latest/download/deno-${deno_target}.zip" -o /tmp/deno.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod 0755 /usr/local/bin/deno \
    && deno --version \
    && rm -f /tmp/deno.zip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar e instalar requirements.txt
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --upgrade --pre "yt-dlp[default]"

# Copiar scripts auxiliares e pré-baixar os modelos (Whisper Medium e Demucs htdemucs_ft)
COPY download_models.py .
COPY demucs_runner.py .
RUN python download_models.py && rm download_models.py

# Copiar código-fonte da aplicação
COPY . .

# Criar os diretórios de upload e saída que serão mapeados
RUN mkdir -p /data/input /data/output

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
