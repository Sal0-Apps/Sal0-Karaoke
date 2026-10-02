"""Decode through FFmpeg so Whisper does not depend on PyAV's open API."""
import subprocess
import numpy as np
import process_manager as pm


def load_whisper_audio(path):
    """Return mono 16 kHz float32 PCM, matching Whisper's input contract."""
    pm.check_cancelled()
    process = subprocess.Popen([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
        "-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
        "-af", "aresample=16000:filter_size=64:cutoff=0.95:rematrix_maxval=1",
        "-f", "f32le", "-acodec", "pcm_f32le", "pipe:1",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pm.set_active_process(process)
    try:
        output, errors = process.communicate()
        pm.check_cancelled()
        if process.returncode:
            detail = errors.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Não foi possível abrir o áudio para o Whisper: {detail}")
        if not output or len(output) % 4:
            raise RuntimeError("O áudio para o Whisper está vazio ou contém PCM inválido.")
        audio = np.frombuffer(output, dtype="<f4").copy()
        if not np.isfinite(audio).all():
            raise RuntimeError("O áudio para o Whisper contém amostras inválidas.")
        return audio
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        pm.clear_active_process()
