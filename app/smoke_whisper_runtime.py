"""Real CPU decode/inference in the release image, without downloading a model."""
import json
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
    for guidance_retry in (False, True):
        progress = []
        result, info = transcribe_vocals(str(audio), model_size="medium", cpu_threads=2,
                                       quality_mode="max_quality", return_info=True, guidance_retry=guidance_retry,
                                       initial_prompt="[00:50]Uma letra serve como guia",
                                       guide_vocabulary="letra guia", enable_vad=False,
                                       progress_callback=lambda percent, *_: progress.append(percent))
        assert isinstance(result, list) and info["language"]
        assert progress and progress[-1] == 100
        assert info['runtime']['cpu_threads'] <= 2
        assert info['runtime']['compute_type'] == 'float32'
        assert info['runtime']['beam_size'] == (15 if guidance_retry else 10)
        assert info['runtime']['guidance_retry'] == guidance_retry
        print(json.dumps({'engine':'Whisper CPU', 'runtime':info['runtime']}), flush=True)
print("Whisper: duas passagens, áudio completo, precisão FP32 e orçamento de CPU validados em inferência real.")
