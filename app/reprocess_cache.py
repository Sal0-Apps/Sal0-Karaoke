"""Reutilização de insumos, nunca de checkpoints de outra tarefa."""
import os
import shutil


def copy_reusable_inputs(source, destination):
    """Novas tarefas reaproveitam áudio caro, mas refazem revisão e renderização.

    Retomadas após pausa continuam usando a pasta isolada da mesma tarefa e
    não passam por esta função. Checkpoints, ASS e resultados não são copiados.
    """
    allowed = {'cache_meta.json', 'original_converted.wav', 'vocals.wav',
               'instrumental.wav', 'transcribed_segments.json'}
    os.makedirs(destination, exist_ok=True)
    for name in os.listdir(source):
        path = os.path.join(source, name)
        if os.path.isfile(path) and (name in allowed or name.startswith(('original_input.', 'original_bg.'))):
            shutil.copy2(path, os.path.join(destination, name))
