import copy
import secrets

EFFECTS = {
    'double_reward': dict(title='Двойная награда', description='За верный ответ — двойная стоимость. Штраф обычный.', reward=2, penalty=1),
    'shield': dict(title='Защита от штрафа', description='За неверный ответ очки не снимаются.', reward=1, penalty=0),
    'half_reward': dict(title='Половина награды', description='Верный ответ приносит половину стоимости. Штраф обычный.', reward=.5, penalty=1),
    'double_penalty': dict(title='Двойной штраф', description='Неверный ответ снимает двойную стоимость. Награда обычная.', reward=1, penalty=2),
}


def apply_event(s, event):
    effect = event['effect']
    candidates = ['double_reward', 'shield'] if effect['type'] == 'random_buff' else ['half_reward', 'double_penalty']
    kind = secrets.choice(candidates)
    players = [p for p in s['players'] if p['id'] != s['host']]
    targets = [secrets.choice(players)] if effect['target'] == 'random_player' else players
    for p in targets:
        s.setdefault('modifiers', {})[p['id']] = dict(kind=kind, remaining=effect['questions'])
    return dict(event_title=event['title'], text=event['text'], kind=kind, **EFFECTS[kind],
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
    effect = EFFECTS[modifier['kind']] if modifier else dict(reward=1, penalty=1)
    return int(value * effect['reward']) if correct else -int(value * effect['penalty'])
