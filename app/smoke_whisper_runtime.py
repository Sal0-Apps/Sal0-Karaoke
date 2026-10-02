"""Real CPU decode/inference in the release image, without downloading a model."""
import tempfile
import subprocess
from pathlib import Path
from transcriber import transcribe_vocals, get_model_local_dir

assert get_model_local_dir("medium"), "O modelo medium deve estar pré-instalado"
with tempfile.TemporaryDirectory() as directory:
    audio = Path(directory) / "lead_vocals.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-ar", "44100", "-ac", "2",
                    str(audio)], check=True)
    progress = []
    result, info = transcribe_vocals(str(audio), model_size="medium", cpu_threads=2,
                                   quality_mode="max_quality", return_info=True, progress_callback=lambda percent, *_: progress.append(percent))
    assert isinstance(result, list) and info["language"]
    assert progress and progress[-1] == 100
print("Whisper: WAV stereo 44,1 kHz convertido e inferência real em CPU concluída.")
