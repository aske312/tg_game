import copy
import json

import pytest
from fastapi.testclient import TestClient

from app.pack_validation import PublicationError, publication_issues
from app.packs import load_pack
from builder.auth import hash_password
from builder.main import create_app
from builder.store import Catalog


def document():
    stages = [dict(id=f's{i}', title=f'Раунд {i}', type='blitz') for i in range(1, 5)]
    questions = [dict(id=f'q{i}', stage=s['id'], type='question', text='Вопрос', answer='Ответ')
                 for i, s in enumerate([stages[0]] * 7 + [stages[1]] * 7 + [stages[2]] * 8, 1)]
    questions += [dict(id='trap', stage='s4', type='event', title='', text='', effect=dict(type='double_penalty', target='all_players', questions=1)),
                  dict(id='last', stage='s4', type='question', text='', answer='')]
    return dict(schema_version=1, title='Игра', stages=stages, rounds=questions)


def test_all_missing_fields_include_stage_and_local_item_number(tmp_path):
    doc = document()
    doc['stages'][3]['title'] = ''
    issues = publication_issues(doc)
    assert len(issues) == 4
    assert {(i['item_id'], i['field']) for i in issues} == {(None, 'title'), ('trap', 'title'), ('last', 'text'), ('last', 'answer')}
    event = next(i for i in issues if i['item_id'] == 'trap')
    assert event['location'] == 'Раунд 4 → Событие 1'
    assert event['stage_index'] == 3 and event['item_index'] == 22
    assert event['message'] == 'Заполните поле «Название события».'
    (tmp_path / 'game.json').write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(PublicationError) as error:
        load_pack(tmp_path)
    assert error.value.issues == issues
    assert 'Раунд 23' not in str(error.value) and 'title/text' not in str(error.value)


def test_optional_event_description_and_legacy_defaults_are_accepted():
    doc = dict(title='Game', rounds=[dict(type='question', text='?', answer='Yes'), dict(type='event', effect=dict(type='shield', target='all_players', questions=1))])
    assert publication_issues(doc) == []


def test_parameters_answers_categories_and_missing_media_identify_fields(tmp_path):
    doc = document()
    doc['rounds'][-2].update(title='Trap', effect=dict(type='reward_multiplier', factor=0, target='unknown', questions=0))
    doc['rounds'][-1].update(text='?', choices=['Да', 'Да'], correct_choice=3, points=-1, time_limit=0, media=dict(type='audio', file='missing.mp3', start=20, end=10))
    issues = publication_issues(doc, tmp_path)
    assert {i['field'] for i in issues} == {'effect.value', 'effect.target', 'effect.questions', 'choices.1', 'correct_choice', 'points', 'time_limit', 'media.file', 'media.end'}
    doc['stages'][3].update(type='grid', categories=[''])
    issues = publication_issues(doc)
    assert any(i['field'] == 'categories' for i in issues)
    assert any(i['field'] == 'category' and i['item_id'] == 'last' for i in issues)


def test_validate_is_read_only_and_publish_returns_field_errors(tmp_path):
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    snapshot = catalog.create('Game')
    good = dict(title='Game', rounds=[dict(id='q', type='question', text='?', answer='Yes')])
    snapshot = catalog.save(snapshot['id'], good, snapshot['revision'])
    snapshot = catalog.publish(snapshot['id'], snapshot['revision'])
    before = (catalog.published_folder(snapshot['id'])/'game.json').read_bytes()
    bad = document()
    with TestClient(create_app(catalog, hash_password('password'))) as client:
        path = '/api/games/'+snapshot['id']
        assert client.post(path+'/validate', json=dict(document=bad, revision=snapshot['revision']), headers={'X-Builder-Request':'1'}).status_code == 401
        client.headers['X-Builder-Request'] = '1'
        client.post('/api/login', json=dict(password='password')).raise_for_status()
        result = client.post(path+'/validate', json=dict(document=bad, revision=snapshot['revision']))
        assert result.status_code == 200 and len(result.json()['issues']) == 3
        assert catalog.snapshot(snapshot['id'])['revision'] == snapshot['revision']
        saved = client.put(path, json=dict(document=bad, revision=snapshot['revision'])).json()
        result = client.post(path+'/publish', json=dict(revision=saved['revision']))
        assert result.status_code == 400
        assert len(result.json()['detail']['issues']) == 3
        assert result.json()['detail']['issues'][0]['location'] == 'Раунд 4 «Раунд 4» → Событие 1'
        assert (catalog.published_folder(snapshot['id'])/'game.json').read_bytes() == before
        fixed = copy.deepcopy(bad)
        fixed['rounds'][-2]['title'] = 'Trap'
        fixed['rounds'][-1].update(text='?', answer='Yes')
        saved = client.put(path, json=dict(document=fixed, revision=saved['revision'])).json()
        assert client.post(path+'/publish', json=dict(revision=saved['revision'])).status_code == 200
