"""Field-level publication errors shared by the pack loader and builder."""
from pathlib import Path

from app.events import normalize_effect, EVENT_TYPES, EVENT_TARGETS
from app.limits import integer, finite_number
from app.modes import LEGACY_STAGE, TITLES
from app.game_settings import QUESTION_DEFAULTS


class PublicationError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('\n'.join(f"{issue['location']}: {issue['message']}" for issue in issues))


def publication_issues(doc, directory=None):
    issues = []
    stages = doc.get('stages', [LEGACY_STAGE])
    items = doc.get('rounds', [])
    if isinstance(stages, list) and not stages:
        return [dict(field='stages', message='Добавьте хотя бы один раунд.', location='Об игре',
                     stage_index=None, stage_id=None, item_index=None, item_id=None)]
    if not isinstance(stages, list) or any(not isinstance(s, dict) for s in stages) or not isinstance(items, list):
        return issues  # Structural errors are handled by the pack loader.

    def add(field, message, stage_index=None, item_index=None):
        s = stages[stage_index] if stage_index is not None else None
        location = 'Об игре'
        if s:
            location = f'Раунд {stage_index + 1}'
            if isinstance(s.get('title'), str) and s['title'].strip():
                location += f' «{s["title"].strip()}»'
        q = items[item_index] if item_index is not None else None
        if q:
            position = sum(isinstance(item, dict) and item.get('stage', stages[0].get('id')) == q.get('stage', stages[0].get('id')) for item in items[:item_index + 1])
            location += f" → {'Событие' if q.get('type') == 'event' else 'Вопрос'} {position}"
        issues.append(dict(field=field, message=message, location=location, stage_index=stage_index, item_index=item_index,
                           stage_id=s.get('id') if s else None, item_id=q.get('id') if q else None))

    def text(value, field, label, limit, si=None, qi=None, required=True):
        if required and (not isinstance(value, str) or not value.strip()):
            add(field, f'Заполните поле «{label}».', si, qi)
        elif not isinstance(value, str) or len(value) > limit:
            add(field, f'Поле «{label}»: не больше {limit} символов.', si, qi)

    def number(value, field, label, si, qi, minimum=1):
        try:
            integer(value, label, minimum=minimum)
        except ValueError:
            add(field, f'Поле «{label}»: укажите целое число не меньше {minimum}.', si, qi)

    text(doc.get('title'), 'title', 'Название игры', 100)
    settings = doc.get('settings', {})
    if not isinstance(settings, dict):
        add('settings', 'Проверьте настройки игры.')
        settings = {}
    for key, default in QUESTION_DEFAULTS.items():
        number(settings.get(key, default), 'settings.' + key,
               'Очки за вопрос' if key == 'points' else 'Время ответа', None, None,
               minimum=0 if key == 'points' else 1)
    stage_map = {s.get('id'): i for i, s in enumerate(stages) if isinstance(s, dict) and isinstance(s.get('id'), str)}
    for si, s in enumerate(stages):
        if not isinstance(s, dict):
            continue
        text(s.get('title', TITLES.get(s.get('type'), 'Раунд') if isinstance(s.get('type'), str) else 'Раунд'), 'title', 'Название раунда', 100, si)
        if not any(isinstance(q, dict) and q.get('stage', stages[0].get('id')) == s.get('id') and q.get('type') == 'question' for q in items):
            add('questions', 'Добавьте хотя бы один вопрос в раунд.', si)
        if s.get('type') == 'grid':
            if s.get('answer_mode', 'all') not in ('all', 'single'):
                add('answer_mode', 'Выберите, кто отвечает: все игроки или один.', si)
            categories = s.get('categories', list(dict.fromkeys(q['category'].strip() for q in items if isinstance(q, dict) and q.get('stage', stages[0].get('id')) == s.get('id') and isinstance(q.get('category'), str) and q['category'].strip())))
            if not isinstance(categories, list) or not categories or any(not isinstance(c, str) or not c.strip() or len(c.strip()) > 100 for c in categories) or len(categories) > 100:
                add('categories', 'Добавьте категории сетки: от 1 до 100 непустых названий длиной до 100 символов.', si)
            elif len({c.strip().casefold() for c in categories}) != len(categories):
                add('categories', 'Названия категорий должны различаться.', si)

    for qi, q in enumerate(items):
        if not isinstance(q, dict) or not stages or not isinstance(stages[0], dict):
            continue
        sid = q.get('stage', stages[0].get('id'))
        si = stage_map.get(sid) if isinstance(sid, str) else None
        if si is None:
            continue
        s = stages[si]
        if q.get('type') == 'event':
            text(q.get('title', 'Событие'), 'title', 'Название события', 100, si, qi)
            text(q.get('text', ''), 'text', 'Описание события', 2000, si, qi, required=False)
            effect = q.get('effect')
            if not isinstance(effect, dict):
                add('effect.type', 'Выберите эффект события.', si, qi)
                continue
            kind, target = effect.get('type'), effect.get('target')
            if not isinstance(kind, str) or kind not in EVENT_TYPES:
                add('effect.type', 'Выберите, что изменится в событии.', si, qi)
            if not isinstance(target, str) or target not in EVENT_TARGETS:
                add('effect.target', 'Выберите, кому достанется эффект.', si, qi)
            number(effect.get('questions', 1), 'effect.questions', 'Длительность, вопросов', si, qi)
            if kind in ('reward_multiplier', 'reward_reduction', 'penalty_multiplier', 'bonus_points', 'penalty_points'):
                try:
                    normalize_effect(dict(effect, target='all_players', questions=1))
                except ValueError:
                    instruction = 'укажите целое число очков от 1' if kind in ('bonus_points', 'penalty_points') else 'укажите долю награды от 0 до 100%' if kind == 'reward_reduction' else 'укажите множитель от 1'
                    add('effect.value', f'Поле «Величина эффекта»: {instruction}.', si, qi)
            if s.get('type') == 'grid':
                add('type', 'Перенесите событие в блиц или выбор из двух: в сетке доступны только вопросы.', si, qi)
            continue
        if q.get('type') != 'question':
            continue
        text(q.get('text'), 'text', 'Текст вопроса', 2000, si, qi)
        binary = s.get('type') == 'binary' or 'choices' in q
        if binary:
            choices = q.get('choices')
            for index, label in enumerate(('Первый вариант', 'Второй вариант')):
                text(choices[index] if isinstance(choices, list) and len(choices) > index else None, f'choices.{index}', label, 100, si, qi)
            if isinstance(choices, list) and len(choices) == 2 and all(isinstance(c, str) and c.strip() for c in choices) and choices[0].strip().casefold() == choices[1].strip().casefold():
                add('choices.1', 'Второй вариант должен отличаться от первого.', si, qi)
            if type(q.get('correct_choice')) is not int or q['correct_choice'] not in (0, 1):
                add('correct_choice', 'Выберите правильный вариант ответа.', si, qi)
        else:
            text(q.get('answer'), 'answer', 'Правильный ответ', 500, si, qi)
        if 'points' in q:
            number(q['points'], 'points', 'Очки', si, qi, minimum=0)
        if 'time_limit' in q:
            number(q['time_limit'], 'time_limit', 'Время, сек.', si, qi)
        accepted = q.get('accepted_answers', [])
        if not isinstance(accepted, list) or len(accepted) > 20 or any(not isinstance(a, str) or not a.strip() or len(a) > 500 for a in accepted):
            add('accepted_answers', 'Укажите не больше 20 допустимых ответов, каждый — от 1 до 500 символов.', si, qi)
        if s.get('type') == 'grid':
            categories = s.get('categories', [item.get('category', '') for item in items if isinstance(item, dict) and item.get('stage', stages[0].get('id')) == sid])
            category = q.get('category')
            if not isinstance(category, str) or not category.strip() or len(category.strip()) > 100 or not isinstance(categories, list) or not any(isinstance(c, str) and c.strip().casefold() == category.strip().casefold() for c in categories):
                add('category', 'Выберите категорию из списка категорий этого раунда.', si, qi)
        media = q.get('media')
        if media is None:
            continue
        if not isinstance(media, dict) or media.get('type') not in ('image', 'audio', 'video'):
            add('media.type', 'Выберите тип медиаматериала.', si, qi)
            continue
        filename = media.get('file')
        if type(media.get('audio_only', False)) is not bool or media.get('audio_only') and media['type'] != 'video':
            add('media.audio_only', 'Режим «только звук» доступен для видео. Включите или выключите переключатель.', si, qi)
        if not isinstance(filename, str) or not filename.strip():
            add('media.file', 'Загрузите файл материала или выберите «Без материала».', si, qi)
        elif directory is not None:
            root = Path(directory).resolve()
            file = (root / filename).resolve()
            if not file.is_relative_to(root) or not file.is_file():
                add('media.file', 'Файл материала не найден. Загрузите его заново.', si, qi)
        start, end = media.get('start', 0), media.get('end')
        valid_start = True
        for value, field, label in [(start, 'media.start', 'Начало отрывка'), (end, 'media.end', 'Конец отрывка')]:
            if value is None and field == 'media.end':
                continue
            try:
                finite_number(value, label)
            except ValueError:
                add(field, f'Поле «{label}»: укажите время не меньше нуля.', si, qi)
                if field == 'media.start':
                    valid_start = False
        if valid_start and type(end) in (int, float) and end <= start:
            add('media.end', 'Конец отрывка должен быть позже начала.', si, qi)
    return issues
