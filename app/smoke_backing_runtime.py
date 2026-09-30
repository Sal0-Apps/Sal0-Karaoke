"""Release smoke check for CPU model inference and generated stem files."""
import os
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
    if torch.cuda.is_available():
        raise RuntimeError('The smoke check must run on CPU.')
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        samples = np.arange(44100 * 2) / 44100
        signal = 0.1 * np.sin(2 * np.pi * 440 * samples) + 0.05 * np.sin(2 * np.pi * 660 * samples)
        source = root / 'vocals.wav'
        sf.write(source, np.column_stack((signal, signal)), 44100)
        separate_backing(str(source), str(root), str(root / 'models'))
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
