"""Keep backing vocals without mixing the original lead voice back in."""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import process_manager as pm
from audio_processor import get_effective_cpu_count

BACKING_MODEL_VERSION = "UVR-BVE-4B_SN-44100-2"


def run_cancellable(command, env=None, progress_callback=None):
    pm.check_cancelled()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, env=env)
    pm.set_active_process(process)
    try:
        import logging
        logger = logging.getLogger("karaoke")
        last_progress = -1
        inference_started = False
        for line in process.stdout:
            if pm.cancel_event.is_set():
                process.terminate()
                break
            if "SAL0_BVE_INFERENCE_START" in line:
                inference_started = True
            if progress_callback and inference_started:
                match = re.search(r"(?<!\d)(\d{1,3})%", line)
                if match:
                    percent = max(0, min(100, int(match.group(1))))
                    if percent > last_progress:
                        progress_callback(percent)
                        last_progress = percent
            if line.strip():
                logger.info("[Backing vocals] %s", line.strip())
        process.wait()
        pm.check_cancelled()
        if process.returncode:
            raise RuntimeError("Falha na separação de backing vocals. Consulte os logs ou desative a opção para tentar novamente.")
    finally:
        process.stdout.close()
        pm.clear_active_process()


def mix_backing(instrumental, backing, output, gain=1.0):
    if not 0 <= float(gain) <= 1:
        raise ValueError("Volume dos backing vocals deve estar entre 0 e 100%.")
    # Sum the separated backing stem into the clean instrumental. No original
    # mix/lead vocal input, no amix normalization that would halve the music.
    run_cancellable([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", instrumental, "-i", backing,
        "-filter_complex",
        f"[1:a]volume={float(gain)}[back];[0:a][back]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=false:latency=1[out]",
        "-map", "[out]", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", output,
    ])


def preserve_backing_vocals(vocals, instrumental, cache_dir, gain=1.0, update_callback=None):
    lead = os.path.join(cache_dir, "lead_vocals.wav")
    backing = os.path.join(cache_dir, "backing_vocals.wav")
    output = os.path.join(cache_dir, "instrumental_with_backing.wav")
    marker = os.path.join(cache_dir, "backing_model_version.txt")
    ready = (
        os.path.isfile(marker) and Path(marker).read_text() == BACKING_MODEL_VERSION
        and all(os.path.isfile(p) and os.path.getsize(p) > 44 for p in (lead, backing))
    )
    if not ready:
        if update_callback:
            update_callback("processing", "Separando backing vocals", 56, stage_progress=0,
                            stage_detail="Separando voz principal e vozes de apoio localmente em CPU")
        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = "-1"
        threads = str(max(1, get_effective_cpu_count() - 1))
        for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            env[key] = threads
        env["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
        def inference_progress(percent):
            if update_callback:
                update_callback("processing", "Separando backing vocals", 56 + round(percent * 0.03),
                                stage_progress=round(percent * 0.9),
                                stage_detail="Analisando voz principal e vozes de apoio em CPU")
        with tempfile.TemporaryDirectory(dir=cache_dir, prefix="backing-") as folder:
            run_cancellable([
                sys.executable, str(Path(__file__).with_name("backing_vocals_runner.py")),
                vocals, folder, "/data/output/models/backing_vocals",
            ], env=env, progress_callback=inference_progress)
            pm.check_cancelled()
            # Only commit complete stem pairs; cancellation cannot create a valid cache marker.
            os.replace(os.path.join(folder, "lead_vocals.wav"), lead)
            os.replace(os.path.join(folder, "backing_vocals.wav"), backing)
            Path(marker).write_text(BACKING_MODEL_VERSION)
    if update_callback:
        update_callback("processing", "Misturando backing vocals", 59, stage_progress=90,
                        stage_detail="Aplicando o volume das vozes de apoio ao instrumental")
    with tempfile.TemporaryDirectory(dir=cache_dir, prefix="backing-mix-") as folder:
        mixed = os.path.join(folder, "mixed.wav")
        mix_backing(instrumental, backing, mixed, gain)
        pm.check_cancelled()
        os.replace(mixed, output)
    if update_callback:
        update_callback("processing", "Backing vocals preservados", 60, stage_progress=100,
                        stage_detail="Instrumental + vozes de apoio; voz principal separada")
    return lead, output
