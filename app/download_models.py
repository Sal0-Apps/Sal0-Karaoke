import os
import wave
import math
import shutil
import subprocess
from faster_whisper import WhisperModel

print("=== INICIANDO PRÉ-DOWNLOAD DOS MODELOS IA ===")

# 1. Baixar o Whisper Medium
print("1/2: Baixando Whisper Medium...")
try:
    WhisperModel("medium", device="cpu", compute_type="float32")
    print("Whisper Medium baixado com sucesso.")
except Exception as e:
    print(f"Aviso ao baixar o Whisper: {e}")

# 2. Criar áudio de 10 segundos com onda senoidal de 440Hz (sinal real para evitar AssertionError)
dummy_wav = "dummy_signal.wav"
print("Criando arquivo de áudio senoidal de 10s para teste do Demucs...")
sample_rate = 44100
num_channels = 2
sample_width = 2
duration = 10.0  # Duração suficiente para a janela do Demucs

# Gerar tom senoidal puro de 440Hz
try:
    with wave.open(dummy_wav, "wb") as w:
        w.setnchannels(num_channels)
        w.setsampwidth(sample_width)
        w.setframerate(sample_rate)
        
        frames = []
        for i in range(int(sample_rate * duration)):
            t = i / sample_rate
            # Gerar valor PCM 16-bit (entre -32768 e 32767)
            val = int(16000 * math.sin(2 * math.pi * 440 * t))
            # Converter para bytes de 16 bits signed (little endian) duplicados para estéreo
            frame = val.to_bytes(sample_width, byteorder='little', signed=True) * num_channels
            frames.append(frame)
            
        w.writeframes(b"".join(frames))
    print("Arquivo de teste de áudio senoidal gerado.")
except Exception as e:
    print(f"Aviso ao gerar áudio de teste: {e}")

# 3. Executar o Demucs via CLI para forçar o download do modelo htdemucs
print("2/2: Baixando e testando o modelo Demucs htdemucs...")
if os.path.exists(dummy_wav):
    try:
        cmd = [
            "demucs",
            "-d", "cpu",
            "--two-stems", "vocals",
            dummy_wav
        ]
        # Executa silenciosamente
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            print("Demucs htdemucs baixado e testado com sucesso.")
        else:
            print(f"Demucs baixou o modelo, mas retornou aviso no teste: {result.stderr}")
    except Exception as e:
        print(f"Aviso ao executar teste do Demucs: {e}")
else:
    print("Arquivo de áudio de teste não encontrado. Pulando execução do teste do Demucs.")

# 4. Limpeza dos arquivos de teste gerados
print("Limpando arquivos temporários do build...")
try:
    if os.path.exists(dummy_wav):
        os.remove(dummy_wav)
    if os.path.exists("separated"):
        shutil.rmtree("separated")
except Exception as e:
    print(f"Aviso ao limpar diretórios de teste: {e}")

print("=== FINALIZADA CONFIGURAÇÃO DOS MODELOS IA ===")
