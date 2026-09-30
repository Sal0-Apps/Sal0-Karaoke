"""Release smoke check for CPU model inference and generated stem files."""
import os
import io
from contextlib import redirect_stdout
import tempfile
from pathlib import Path

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '2'
os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'


def main():
    import numpy as np
    import soundfile as sf
    import torch
    from backing_vocals_runner import separate_backing
    from backing_progress import read_progress_event
    if torch.cuda.is_available():
        raise RuntimeError('The smoke check must run on CPU.')
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        samples = np.arange(44100 * 2) / 44100
        signal = 0.1 * np.sin(2 * np.pi * 440 * samples) + 0.05 * np.sin(2 * np.pi * 660 * samples)
        source = root / 'vocals.wav'
        sf.write(source, np.column_stack((signal, signal)), 44100)
        progress_log = io.StringIO()
        with redirect_stdout(progress_log):
            separate_backing(str(source), str(root), str(root / 'models'))
        events = [event for line in progress_log.getvalue().splitlines()
                  if (event := read_progress_event(line)) is not None]
        phases = {phase for phase, _ in events}
        if not {'preparing_audio','preparing_windows','inference','reconstructing','complete'} <= phases:
            raise RuntimeError('VR progress did not distinguish preparation from inference.')
        inference = [percent for phase,percent in events if phase == 'inference']
        if not inference or inference[0] != 0 or inference[-1] != 100:
            raise RuntimeError('Inference did not report its own 0–100% progress.')
        print('Real VR preparation, inference and reconstruction progress validated.')
        for filename in ('lead_vocals.wav', 'backing_vocals.wav'):
            audio, rate = sf.read(root / filename)
            if rate != 44100 or abs(len(audio) - len(samples)) > 441 or not np.isfinite(audio).all():
                raise RuntimeError('Invalid stem: ' + filename)
        print('CPU BVE inference and both output stems validated.')
    import main as karaoke
    if not any(route.path == '/api/youtube/publication-options' for route in karaoke.app.routes):
        raise RuntimeError('YouTube routes were not registered.')
    print('Application imports and publication routes validated.')


if __name__ == '__main__':
    main()
