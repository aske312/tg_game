import copy
import secrets
from fractions import Fraction
from app.modes import LEGACY_STAGE

from app.limits import integer, finite_number

EFFECTS = {
    'double_reward': dict(title='Двойная награда', description='За верный ответ — двойная стоимость. Штраф обычный.', reward=2, penalty=1),
    'shield': dict(title='Защита от штрафа', description='За неверный ответ очки не снимаются.', reward=1, penalty=0),
    'half_reward': dict(title='Половина награды', description='Верный ответ приносит половину стоимости. Штраф обычный.', reward=.5, penalty=1),
    'double_penalty': dict(title='Двойной штраф', description='Неверный ответ снимает двойную стоимость. Награда обычная.', reward=1, penalty=2),
}

CUSTOM_EFFECTS = {'reward_multiplier', 'reward_reduction', 'penalty_multiplier', 'bonus_points', 'penalty_points'}
EVENT_TYPES = set(EFFECTS) | CUSTOM_EFFECTS | {'random_buff', 'random_debuff'}
EVENT_TARGETS = {'random_player', 'all_players', 'leader', 'last_player'}


def normalize_effect(effect):
    if not isinstance(effect, dict) or not isinstance(effect.get('type'), str) or effect['type'] not in EVENT_TYPES or not isinstance(effect.get('target'), str) or effect['target'] not in EVENT_TARGETS:
        raise ValueError('Укажите поддерживаемый эффект и его получателей')
    result = dict(type=effect['type'], target=effect['target'], questions=integer(effect.get('questions', 1), 'Длительность эффекта'))
    kind = effect['type']
    if kind in ('reward_multiplier', 'penalty_multiplier', 'reward_reduction'):
        result['factor'] = finite_number(effect.get('factor'), 'Множитель', minimum=0 if kind=='reward_reduction' else 1, maximum=1 if kind=='reward_reduction' else None)
    if kind in ('bonus_points', 'penalty_points'):
        result['amount'] = integer(effect.get('amount'), 'Величина эффекта')
    return result


def describe_effect(effect):
    kind = effect['type']
    if kind in EFFECTS:
        return dict(EFFECTS[kind])
    result = dict(reward=1, penalty=1, bonus=0, extra_penalty=0)
    if kind in ('reward_multiplier', 'reward_reduction'):
        factor = effect['factor']
        result.update(reward=factor, title=f'Награда ×{factor:g}', description=f'За верный ответ — {factor:g} стоимости вопроса. Штраф обычный.')
    elif kind == 'penalty_multiplier':
        factor = effect['factor']
        result.update(penalty=factor, title=f'Штраф ×{factor:g}', description=f'За неверный ответ снимается {factor:g} стоимости вопроса. Награда обычная.')
    elif kind == 'bonus_points':
        amount = effect['amount']
        result.update(bonus=amount, title=f'Бонус +{amount}', description=f'Каждый верный ответ приносит дополнительно {amount} очков. Штраф обычный.')
    elif kind == 'penalty_points':
        amount = effect['amount']
        result.update(extra_penalty=amount, title=f'Штраф +{amount}', description=f'Каждый неверный ответ снимает дополнительно {amount} очков. Награда обычная.')
    else:
        raise ValueError('Неизвестный эффект')
    return result


def apply_event(s, event):
    effect = normalize_effect(event['effect'])
    kind = effect['type']
    if kind in ('random_buff', 'random_debuff'):
        kind = secrets.choice(['double_reward', 'shield'] if kind == 'random_buff' else ['half_reward', 'double_penalty'])
    parameters = {key:effect[key] for key in ('factor','amount') if key in effect}
    details = describe_effect(dict(type=kind, **parameters))
    players = [p for p in s['players'] if p['id'] != s['host']]
    if effect['target'] in ('leader','last_player') and players:
        score = (max if effect['target']=='leader' else min)(p['score'] for p in players)
        players = [p for p in players if p['score']==score]
    targets = [secrets.choice(players)] if players and effect['target'] != 'all_players' else players
    for p in targets:
        s.setdefault('modifiers', {})[p['id']] = dict(kind=kind, remaining=effect['questions'], title=details['title'], **parameters)
    return dict(event_title=event['title'], text=event.get('text',''), kind=kind, **details,
                targets=[p['name'] for p in targets], questions=effect['questions'])


def snapshot_modifiers(s):
    s['round_modifiers'] = copy.deepcopy(s.get('modifiers', {}))


def consume_modifiers(s):
    for uid, modifier in list(s.get('modifiers', {}).items()):
        modifier['remaining'] -= 1
        if modifier['remaining'] <= 0:
            del s['modifiers'][uid]


def score_delta(s, uid, value, correct):
    modifier = s.get('round_modifiers', {}).get(uid)
    effect = describe_effect(dict(modifier, type=modifier['kind'])) if modifier else dict(reward=1, penalty=1)
    if correct:
        return int(value * Fraction(str(effect['reward']))) + effect.get('bonus', 0)
    stage = s.get('stages', [LEGACY_STAGE])[s.get('stage_index', 0)]
    base = value if stage.get('answer_penalties', True) else 0
    multiplier = effect['penalty']
    # Shields still protect; disabling traps removes only their added penalty.
    extra = 0
    if stage.get('trap_penalties', True):
        extra = max(0, int(value * Fraction(str(multiplier))) - value) + effect.get('extra_penalty', 0)
    if multiplier < 1:
        base = int(base * Fraction(str(multiplier)))
    return -base - extra
