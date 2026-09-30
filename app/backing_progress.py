"""Explicit VR substage progress; preparation bars are never inference clocks."""
import json
from contextlib import contextmanager

PREFIX = 'SAL0_BVE_PROGRESS '
PHASES = {'loading_model', 'preparing_audio', 'preparing_windows', 'inference', 'reconstructing', 'complete'}


def emit_progress(phase, percent):
    print('\n' + PREFIX + json.dumps({'phase': phase, 'percent': percent}), flush=True)


def read_progress_event(line):
    if not line.startswith(PREFIX):
        return None
    try:
        event = json.loads(line[len(PREFIX):])
        if not isinstance(event, dict) or event.get('phase') not in PHASES:
            return None
        percent = event.get('percent')
        if percent is not None and (type(percent) is not int or not 0 <= percent <= 100):
            return None
        return event['phase'], percent
    except (TypeError, ValueError):
        return None


@contextmanager
def vr_progress(instance, vr_module=None):
    """Instrument the pinned VR implementation inside its isolated child process.

    loading_mix has a band preparation bar. With TTA disabled, inference_vr
    has two bars: building windows, then predicting masks. Report a completed
    item only after its loop body returns. Reconstruction has no measurable
    continuous progress and stays indeterminate until both stems are verified.
    """
    if vr_module is None:
        from audio_separator.separator.architectures import vr_separator as vr_module
    original_tqdm = vr_module.tqdm
    originals = {name: getattr(instance, name) for name in ('loading_mix', 'inference_vr', 'spec_to_wav')}
    state = {'scope': None, 'bars': 0, 'output_started': False}

    def tracked_tqdm(iterable, *args, **kwargs):
        phase = state['scope']
        if phase == 'inference':
            state['bars'] += 1
            phase = 'preparing_windows' if state['bars'] == 1 else 'inference'
        kwargs['desc'] = {'preparing_audio': 'BVE preparar áudio',
                          'preparing_windows': 'BVE preparar blocos',
                          'inference': 'BVE analisar voz'}.get(phase, 'BVE')
        progress = original_tqdm(iterable, *args, **kwargs)
        total = len(iterable)
        def iterate():
            emit_progress(phase, 0)
            previous = 0
            try:
                for completed, item in enumerate(progress, 1):
                    yield item
                    percent = round(completed * 100 / total) if total else 100
                    if percent != previous:
                        emit_progress(phase, percent)
                        previous = percent
            finally:
                progress.close()
        return iterate()

    def loading_mix(*args, **kwargs):
        state['scope'] = 'preparing_audio'
        return originals['loading_mix'](*args, **kwargs)

    def inference_vr(*args, **kwargs):
        state.update(scope='inference', bars=0)
        return originals['inference_vr'](*args, **kwargs)

    def spec_to_wav(*args, **kwargs):
        if not state['output_started']:
            state['output_started'] = True
            emit_progress('reconstructing', None)
        return originals['spec_to_wav'](*args, **kwargs)

    vr_module.tqdm = tracked_tqdm
    instance.loading_mix, instance.inference_vr, instance.spec_to_wav = loading_mix, inference_vr, spec_to_wav
    try:
        yield
    finally:
        vr_module.tqdm = original_tqdm
        for name, method in originals.items():
            setattr(instance, name, method)
