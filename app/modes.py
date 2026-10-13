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
        parsed = dict(id=sid, type=stage['type'], title=title.strip(), order=order, chooser=chooser, auto_advance=auto)
        if stage['type'] == 'grid':
            categories = stage.get('categories')
            if 'categories' not in stage:
                # Existing grids already contain category names on their questions.
                categories = []
                for q in doc.get('rounds', []):
                    if isinstance(q, dict) and q.get('stage', raw[0]['id']) == sid and isinstance(q.get('category'), str) and q['category'].strip():
                        name = q['category'].strip()
                        if name.casefold() not in {c.casefold() for c in categories}:
                            categories.append(name)
            if not isinstance(categories, list) or not 1 <= len(categories) <= 100 or any(not isinstance(c, str) or not c.strip() or len(c.strip()) > 100 for c in categories):
                raise ValueError(f'Раунд «{title}»: добавьте категории сетки (до 100 названий по 100 символов)')
            categories = [c.strip() for c in categories]
            if len({c.casefold() for c in categories}) != len(categories):
                raise ValueError(f'Раунд «{title}»: названия категорий должны различаться')
            parsed['categories'] = categories
        stages.append(parsed)
    return stages


def grid_category(value, stage):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 100:
        raise ValueError('Выберите обязательную категорию вопроса сетки')
    category = next((c for c in stage.get('categories', []) if c.casefold() == value.strip().casefold()), None)
    if category is None:
        raise ValueError('Категория вопроса должна быть из списка категорий этого раунда')
    return category


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
