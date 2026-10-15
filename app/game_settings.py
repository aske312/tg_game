"""Defaults inherited by questions that do not specify their own values."""
from app.limits import integer

QUESTION_DEFAULTS = dict(time_limit=45, points=100)


def question_defaults(doc):
    settings = doc.get('settings', {})
    if not isinstance(settings, dict):
        raise ValueError('Настройки игры должны быть объектом')
    return {key: integer(settings.get(key, default), key, minimum=0 if key == 'points' else 1)
            for key, default in QUESTION_DEFAULTS.items()}
