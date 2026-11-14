"""Validated per-mode notification choices and literal, safe text templates."""
import html
import re


def normalize(value, modes, events, defaults=None):
    value = {} if value is None else value
    if not isinstance(value, dict):
        raise ValueError('Preferências de mensagens inválidas.')
    defaults = defaults or {}
    enabled = value.get('enabled', True)
    if type(enabled) is not bool:
        raise ValueError('Ativação das mensagens inválida.')
    choices, templates = value.get('modes', {}), value.get('templates', {})
    if not isinstance(choices, dict) or not isinstance(templates, dict):
        raise ValueError('Escolha as mensagens de cada modo.')
    result = {'enabled': enabled, 'modes': {}, 'templates': {}}
    for mode, _ in modes:
        flags, texts = choices.get(mode, {}), templates.get(mode, {})
        if not isinstance(flags, dict) or not isinstance(texts, dict):
            raise ValueError('Configuração de modo inválida.')
        result['modes'][mode], result['templates'][mode] = {}, {}
        for event, _ in events:
            flag = flags.get(event, defaults.get(event, True))
            text = texts.get(event, '')
            if type(flag) is not bool or not isinstance(text, str) or len(text) > 3500:
                raise ValueError('Use opções válidas e textos de até 3.500 caracteres.')
            result['modes'][mode][event] = flag
            result['templates'][mode][event] = text.strip()
    return result


def allowed(policy, mode, event):
    return policy['enabled'] and policy['modes'].get(mode, {}).get(event, False)


def render(template, values, original='', html_values=None):
    """Literal text only; placeholders cannot execute code or inject Telegram HTML."""
    if not template:
        return original
    encoded = html.escape(template)
    html_values = html_values or {}
    return re.sub(r'\{([a-z_]+)\}', lambda match: original if match[1] == 'mensagem'
                  else html_values[match[1]] if match[1] in html_values
                  else html.escape(str(values.get(match[1], match[0]))), encoded)
