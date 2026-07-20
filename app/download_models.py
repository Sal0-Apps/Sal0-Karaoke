import os
import wave
import math
import shutil
import subprocess
from faster_whisper import WhisperModel

print("=== INICIANDO PRÉ-DOWNLOAD DOS MODELOS IA (v4.0.0) ===")

# 1. Baixar os modelos Whisper Large v3 Turbo e Medium pré-instalados na imagem
print("1/3: Baixando Whisper Large v3 Turbo (padrão v4.0.0)...")
try:
    WhisperModel("deepdml/faster-whisper-large-v3-turbo", device="cpu", compute_type="float32")
    print("Whisper Large v3 Turbo pré-instalado com sucesso.")
except Exception as e:
    print(f"Aviso ao baixar o Whisper Large v3 Turbo: {e}")

print("2/3: Baixando Whisper Medium (fallback alternativo v4.0.0)...")
try:
    WhisperModel("medium", device="cpu", compute_type="float32")
    print("Whisper Medium pré-instalado com sucesso.")
except Exception as e:
    print(f"Aviso ao baixar o Whisper Medium: {e}")

# 2. Criar áudio de 10 segundos com onda senoidal para teste do Demucs
dummy_wav = "dummy_signal.wav"
print("Criando arquivo de áudio senoidal de 10s para teste do Demucs...")
sample_rate = 44100
num_channels = 2
sample_width = 2
duration = 10.0

try:
    with wave.open(dummy_wav, "wb") as w:
        w.setnchannels(num_channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        
        frames = []
        for i in range(int(sample_rate * duration)):
            t = i / sample_rate
            val = int(16000 * math.sin(2 * math.pi * 440 * t))
            frame = val.to_bytes(sample_width, byteorder='little', signed=True) * num_channels
            frames.append(frame)
            
        w.writeframes(b"".join(frames))
    print("Arquivo de teste de áudio senoidal gerado.")
except Exception as e:
    print(f"Aviso ao gerar áudio de teste: {e}")

# 3. Executar o Demucs via CLI para forçar o download do modelo htdemucs
print("Testando o modelo Demucs htdemucs...")
if os.path.exists(dummy_wav):
    try:
        cmd = [
            "demucs",
            "-d", "cpu",
            "--two-stems", "vocals",
            dummy_wav
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print("Demucs htdemucs baixado e testado com sucesso.")
        else:
            print(f"Demucs baixou o modelo com avisos: {result.stderr}")
    except Exception as e:
        print(f"Aviso ao executar teste do Demucs: {e}")

# 4. Limpeza dos arquivos temporários de teste
print("Limpando arquivos temporários do build...")
try:
    if os.path.exists(dummy_wav):
        os.remove(dummy_wav)
    if os.path.exists("separated"):
        shutil.rmtree("separated")
except Exception as e:
    print(f"Aviso ao limpar diretórios de teste: {e}")

# 5. Baixar imagens de paisagem padrão para backup offline
print("3/3: Baixando imagens de paisagem padrão para backup offline...")
bg_dir = "default_backgrounds"
os.makedirs(bg_dir, exist_ok=True)
landscape_urls = [
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c5/Moraine_Lake_17092005.jpg/1280px-Moraine_Lake_17092005.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/35/Neckarhalde_T%C3%BCbingen_Ganzaufnahme.jpg/1280px-Neckarhalde_T%C3%BCbingen_Ganzaufnahme.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e0/Fuji_from_Motoshu_2004-11-16.jpg/1280px-Fuji_from_Motoshu_2004-11-16.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/ca/Loch_Lomond_from_Duncryne.jpg/1280px-Loch_Lomond_from_Duncryne.jpg",
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a2/Val_di_Funes_panorama_April_2017.jpg/1280px-Val_di_Funes_panorama_April_2017.jpg"
]
import urllib.request
for idx, url in enumerate(landscape_urls):
    dest = os.path.join(bg_dir, f"landscape_{idx+1}.jpg")
    if not os.path.exists(dest):
        try:
            print(f"Baixando imagem {idx+1} de {len(landscape_urls)}...")
            urllib.request.urlretrieve(url, dest)
            print(f"Imagem {idx+1} salva em {dest}")
        except Exception as e:
            print(f"Aviso ao baixar imagem {idx+1}: {e}")

print("=== FINALIZADA CONFIGURAÇÃO DOS MODELOS IA (v4.0.0) ===")
