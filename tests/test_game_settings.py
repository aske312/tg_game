import copy
import io
import json
import zipfile

import pytest

from app.pack_validation import PublicationError, publication_issues
from app.packs import load_pack
from app.store import Store
from builder.store import Catalog


def document():
    return dict(title='Game', settings=dict(time_limit=25, points=200),
                rounds=[dict(id='inherit', type='question', text='?', answer='Yes'),
                        dict(id='own', type='question', text='?', answer='Yes', time_limit=60, points=0)])


def test_defaults_and_exceptions_are_used_by_live_room(tmp_path, monkeypatch):
    doc = document()
    (tmp_path/'game.json').write_text(json.dumps(doc), encoding='utf-8')
    pack = load_pack(tmp_path)
    assert [(q['seconds'], q['value']) for q in pack['questions']] == [(25, 200), (60, 0)]
    db = Store(tmp_path/'room.sqlite3')
    host, player = dict(id='h', name='Host'), dict(id='p', name='Player')
    code = db.create(host, questions=pack['questions'], stages=pack['stages'])
    db.change(code, player, 'join')
    monkeypatch.setattr('app.store.time.time', lambda: 1000)
    db.change(code, host, 'start')
    if db.read(code)['phase'] == 'intro':
        db.change(code, host, 'next')
    assert db.read(code)['deadline'] == 1025
    db.change(code, player, 'answer', text='Yes')
    db.change(code, host, 'correct', player='p')
    assert next(p for p in db.read(code)['players'] if p['id'] == 'p')['score'] == 200


@pytest.mark.parametrize('settings,field', [(None, 'settings'), ([], 'settings'),
    ({'time_limit': 0}, 'settings.time_limit'), ({'time_limit': True}, 'settings.time_limit'),
    ({'time_limit': 1.5}, 'settings.time_limit'), ({'points': -1}, 'settings.points'),
    ({'points': '100'}, 'settings.points')])
def test_invalid_game_settings_cannot_publish(tmp_path, settings, field):
    doc = document();doc['settings'] = settings
    issues = publication_issues(doc)
    assert any(i['field'] == field and i['item_id'] is None for i in issues)
    (tmp_path/'game.json').write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(PublicationError):
        load_pack(tmp_path)


def test_legacy_questions_keep_previous_defaults(tmp_path):
    doc = document();doc.pop('settings')
    (tmp_path/'game.json').write_text(json.dumps(doc), encoding='utf-8')
    pack = load_pack(tmp_path)
    assert pack['questions'][0]['seconds'] == 45 and pack['questions'][0]['value'] == 100
    assert pack['questions'][1]['seconds'] == 60 and pack['questions'][1]['value'] == 0


def test_settings_survive_draft_publication_export_and_do_not_change_existing_room(tmp_path):
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    snapshot = catalog.create('Game')
    snapshot = catalog.save(snapshot['id'], document(), snapshot['revision'])
    snapshot = catalog.publish(snapshot['id'], snapshot['revision'])
    old = load_pack(catalog.games/snapshot['id'])
    db = Store(tmp_path/'room.sqlite3')
    code = db.create(dict(id='h', name='Host'), questions=old['questions'])
    doc = copy.deepcopy(snapshot['document']);doc['settings']['time_limit'] = 15
    snapshot = catalog.save(snapshot['id'], doc, snapshot['revision'])
    snapshot = catalog.publish(snapshot['id'], snapshot['revision'])
    assert load_pack(catalog.games/snapshot['id'])['questions'][0]['seconds'] == 15
    assert db.read(code)['pack'][0]['seconds'] == 25
    with zipfile.ZipFile(io.BytesIO(catalog.export(snapshot['id']))) as archive:
        exported = json.loads(archive.read('game.json'))
        assert exported['settings']['time_limit'] == 15
        assert 'time_limit' not in exported['rounds'][0]


def test_empty_rounds_draft_stays_empty_and_cannot_publish(tmp_path):
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    snapshot = catalog.create('Empty')
    doc = dict(title='Empty', stages=[], rounds=[])
    snapshot = catalog.save(snapshot['id'], doc, snapshot['revision'])
    assert catalog.open(snapshot['id'])['document'] == doc
    assert publication_issues(doc)[0]['field'] == 'stages'
    with pytest.raises(ValueError):
        catalog.publish(snapshot['id'], snapshot['revision'])
