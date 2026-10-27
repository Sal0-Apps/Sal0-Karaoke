"""Administrator-controlled presentation; never shifts the recording clock."""
import json
import math
import os
from pathlib import Path
import re

CONFIG_PATH = Path('/data/output/karaoke_animation.json')
DEFAULTS = dict(animation_style='smooth', highlight_glow=True,
                instrumental_style='progress', instrumental_color='#38BDF8',
                instrumental_text='Instrumental', instrumental_size=100,
                min_instrumental_gap=2.0, countdown_seconds=3)


def normalize_visuals(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('Configuração de animação inválida.')
    result = {**DEFAULTS, **value}
    if not isinstance(result['animation_style'], str) or result['animation_style'] not in {'classic', 'smooth', 'pulse', 'outline', 'instant'}:
        raise ValueError('Escolha uma animação válida.')
    if not isinstance(result['highlight_glow'], bool):
        raise ValueError('Escolha se o brilho está ativado.')
    if not isinstance(result['instrumental_style'], str) or result['instrumental_style'] not in {'classic', 'progress', 'dots', 'countdown'}:
        raise ValueError('Escolha um estilo de instrumental válido.')
    if not isinstance(result['instrumental_color'], str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', result['instrumental_color']):
        raise ValueError('Escolha uma cor válida para o instrumental.')
    label = result['instrumental_text']
    if (not isinstance(label, str) or not 1 <= len(label.strip()) <= 40
            or any(ord(char) < 32 or ord(char) == 127 or char in '{}\\' for char in label)):
        raise ValueError('Use de 1 a 40 caracteres no aviso, sem quebras de linha, chaves ou barras invertidas.')
    result['instrumental_text'] = label.strip()
    size = result['instrumental_size']
    if isinstance(size, bool) or not isinstance(size, int) or not 60 <= size <= 150:
        raise ValueError('O tamanho do aviso deve ficar entre 60% e 150%.')
    gap = result['min_instrumental_gap']
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap) or not 1.5 <= gap <= 10:
        raise ValueError('O intervalo mínimo deve ficar entre 1,5 e 10 segundos.')
    countdown = result['countdown_seconds']
    if isinstance(countdown, bool) or not isinstance(countdown, int) or not 0 <= countdown <= 5:
        raise ValueError('A contagem deve ficar entre 0 e 5 segundos; use 0 para desativar.')
    return result


def load_visuals(path=None):
    try:
        return normalize_visuals(json.loads(Path(path or CONFIG_PATH).read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return dict(DEFAULTS)


def install_routes(app, get_current_user, require_admin, path=None):
    from fastapi import Depends, HTTPException
    target = Path(path or CONFIG_PATH)

    def admin(user=Depends(get_current_user)):
        require_admin(user)
        return user

    @app.get('/api/admin/karaoke-visuals')
    def get_config(user=Depends(admin)):
        return load_visuals(target)

    @app.post('/api/admin/karaoke-visuals')
    def save_config(options: dict, user=Depends(admin)):
        try:
            result = normalize_visuals(options)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        target.parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            json.dump(result, output, ensure_ascii=False)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return result
