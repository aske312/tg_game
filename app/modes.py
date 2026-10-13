"""Round settings shared by the library, editor and room state."""
import re

LEGACY_STAGE = dict(id='legacy', type='blitz', title='Блиц', order='sequential', chooser='winner', auto_advance=False)
TITLES = dict(blitz='Блиц', grid='Сетка вопросов', binary='Выбор из двух')


def stages_from_doc(doc):
    if 'stages' not in doc:
        return [dict(LEGACY_STAGE)]
    raw = doc['stages']
    if not isinstance(raw, list) or not 1 <= len(raw) <= 30:
        raise ValueError('В stages должно быть от 1 до 30 игровых раундов')
    stages, ids = [], set()
    for index, stage in enumerate(raw, 1):
        if not isinstance(stage, dict) or not isinstance(stage.get('type'), str) or stage['type'] not in TITLES:
            raise ValueError(f'Раунд {index}: режим blitz, grid или binary')
        sid = stage.get('id')
        if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', sid) or sid in ids:
            raise ValueError(f'Раунд {index}: нужен уникальный id')
        ids.add(sid)
        title = stage.get('title', TITLES[stage['type']])
        if not isinstance(title, str) or not title.strip() or len(title) > 100:
            raise ValueError(f'Раунд {index}: название до 100 символов')
        order, chooser, auto = stage.get('order', 'sequential'), stage.get('chooser', 'winner'), stage.get('auto_advance', False)
        if order not in ('sequential', 'random') or chooser not in ('winner', 'host') or type(auto) is not bool:
            raise ValueError(f'Раунд {index}: недопустимые настройки порядка, выбора или перехода')
        stages.append(dict(id=sid, type=stage['type'], title=title.strip(), order=order, chooser=chooser, auto_advance=auto))
    return stages


def binary_fields(item, required=False):
    if not required and 'choices' not in item:
        return {}
    choices, correct = item.get('choices'), item.get('correct_choice')
    if not isinstance(choices, list) or len(choices) != 2 or any(not isinstance(c, str) or not c.strip() or len(c) > 100 for c in choices):
        raise ValueError('Укажите два варианта ответа до 100 символов')
    choices = [c.strip() for c in choices]
    if choices[0].casefold() == choices[1].casefold() or type(correct) is not int or correct not in (0, 1):
        raise ValueError('Варианты должны различаться; correct_choice — 0 или 1')
    return dict(choices=choices, correct_choice=correct, answer=choices[correct], accepted_answers=[])
