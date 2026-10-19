import copy
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.packs import find_pack, list_packs, load_pack
from app.store import Store
from builder.auth import hash_password
from builder.main import create_app
from builder.store import Catalog, Conflict

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def catalog(tmp_path):
    return Catalog(tmp_path/'builder', tmp_path/'games', ROOT/'games')


@pytest.fixture
def client(catalog):
    with TestClient(create_app(catalog, hash_password('editor-password')), headers={'X-Builder-Request':'1'}) as client:
        yield client


def question(answer='4'):
    return dict(id='q1', type='question', text='2+2?', answer=answer, points=100, time_limit=45)


def draft(catalog):
    snapshot = catalog.create('Test game')
    doc = copy.deepcopy(snapshot['document'])
    doc['rounds'] = [question()]
    return catalog.save(snapshot['id'], doc, snapshot['revision'])


def test_author_authentication_and_csrf(client, catalog):
    assert client.get('/api/games').status_code == 401
    assert client.post('/api/login', json={'password':'wrong'}).status_code == 401
    assert client.post('/api/login', json={'password':'editor-password'}, headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/login', json={'password':'editor-password'}).status_code == 200
    assert client.get('/api/games').status_code == 200
    assert 'example-race' in [g['id'] for g in client.get('/api/games').json()]
    assert client.post('/api/rooms',json={}).status_code == 404  # This service has no gameplay endpoints.
    token = client.cookies.get('ratrace_builder')
    assert Catalog(catalog.data,catalog.games,catalog.bundled).authenticated(token)
    assert client.post('/api/logout').status_code == 200
    assert not catalog.authenticated(token)
    assert client.get('/api/games').status_code == 401
    client.headers.pop('X-Builder-Request')
    assert client.post('/api/login',json={'password':'editor-password'}).status_code == 403


def test_login_throttle(client):
    for _ in range(10):
        assert client.post('/api/login',json={'password':'wrong'}).status_code == 401
    assert client.post('/api/login',json={'password':'editor-password'}).status_code == 429


def test_draft_publish_snapshot_and_export(catalog, tmp_path):
    snapshot = draft(catalog)
    game_id = snapshot['id']
    assert not catalog.published_folder(game_id)
    assert snapshot['dirty']
    snapshot = catalog.publish(game_id,snapshot['revision'])
    assert not snapshot['dirty']
    pack = find_pack([catalog.games,catalog.bundled],'library-'+game_id)
    game = Store(tmp_path/'game.sqlite3')
    code = game.create(dict(id='host',name='Host'),questions=pack['questions'])
    doc = copy.deepcopy(snapshot['document'])
    doc['rounds'][0]['answer'] = 'updated'
    edited = catalog.save(game_id,doc,snapshot['revision'])
    assert load_pack(catalog.games/game_id)['questions'][0]['answer'] == '4'
    catalog.publish(game_id,edited['revision'])
    assert load_pack(catalog.games/game_id)['questions'][0]['answer'] == 'updated'
    assert game.read(code)['pack'][0]['answer'] == '4'
    assert list((catalog.data/'backups'/game_id).glob('*.json'))
    with zipfile.ZipFile(io.BytesIO(catalog.export(game_id))) as archive:
        assert json.loads(archive.read('game.json'))['rounds'][0]['answer'] == 'updated'


def test_invalid_publish_does_not_replace_live_game(catalog):
    snapshot = draft(catalog)
    snapshot = catalog.publish(snapshot['id'],snapshot['revision'])
    manifest = catalog.games/snapshot['id']/'game.json'
    original = manifest.read_bytes()
    doc = copy.deepcopy(snapshot['document'])
    doc['rounds'][0]['answer'] = ''
    edited = catalog.save(snapshot['id'],doc,snapshot['revision'])
    with pytest.raises(ValueError):
        catalog.publish(snapshot['id'],edited['revision'])
    assert manifest.read_bytes() == original


def test_optimistic_edit_and_external_publish_conflicts(catalog):
    snapshot = draft(catalog)
    doc = copy.deepcopy(snapshot['document'])
    doc['title'] = 'First author'
    edited = catalog.save(snapshot['id'],doc,snapshot['revision'])
    with pytest.raises(Conflict):
        catalog.save(snapshot['id'],snapshot['document'],snapshot['revision'])
    snapshot = catalog.publish(snapshot['id'],edited['revision'])
    manifest = catalog.games/snapshot['id']/'game.json'
    external = json.loads(manifest.read_text(encoding='utf-8'))
    external['title'] = 'SFTP edit'
    manifest.write_text(json.dumps(external),encoding='utf-8')
    with pytest.raises(Conflict):
        catalog.publish(snapshot['id'],snapshot['revision'])
    restored = catalog.reload(snapshot['id'])
    assert restored['document']['title'] == 'SFTP edit'
    assert not restored['dirty']


def test_bundled_game_edit_preserves_source_and_media(catalog):
    original = (catalog.bundled/'example-race/game.json').read_bytes()
    snapshot = catalog.open('example-race')
    doc = copy.deepcopy(snapshot['document'])
    doc['title'] = 'Edited example'
    saved = catalog.save('example-race',doc,snapshot['revision'])
    catalog.publish('example-race',saved['revision'])
    assert (catalog.bundled/'example-race/game.json').read_bytes() == original
    pack = load_pack(catalog.games/'example-race')
    assert pack['title'] == 'Edited example'
    assert len(pack['questions']) == 6
    for q in pack['questions']:
        if q.get('media'):
            assert Path(q['media']['source']).is_file()
    with zipfile.ZipFile(io.BytesIO(catalog.export('example-race'))) as archive:
        assert len(archive.namelist()) == 4


@pytest.mark.parametrize('kind,filename', [('image', 'red.png'), ('audio', 'signals.wav'), ('video', 'colors.mp4')])
def test_media_upload_and_path_boundaries(client, catalog, monkeypatch, kind, filename):
    client.post('/api/login',json={'password':'editor-password'})
    snapshot = client.post('/api/games',json={'title':'Media test'}).json()
    path = '/api/games/'+snapshot['id']
    assert client.post(path+'/media?kind=image',content=b'<svg/>').status_code == 400
    data = (ROOT/'games/example-race/media'/filename).read_bytes()
    media = client.post(path+'/media?kind='+kind,content=data)
    assert media.status_code == 200
    name = media.json()['file']
    for start in (0, 8, 0, len(data)-8):
        response = client.get(path+'/media',params={'file':name},headers={'Range':f'bytes={start}-{start+7}'})
        assert response.status_code == 206
        assert response.content == data[start:start+8]
        assert response.headers['content-range'] == f'bytes {start}-{start+7}/{len(data)}'
    assert client.get(path+'/media',params={'file':name}).content == data
    for name in ['../../sessions.sqlite3','/etc/passwd','../outside.png']:
        assert client.get(path+'/media',params={'file':name}).status_code == 400
    from builder import main
    monkeypatch.setattr(main,'MAX_MEDIA_BYTES',64)
    assert client.post(path+'/media?kind=image',content=b'x'*65).status_code == 413
    assert not list((catalog.data/'uploads').glob('*.part'))


def test_api_conflict_and_export_validation(client, catalog):
    client.post('/api/login',json={'password':'editor-password'})
    snapshot = client.post('/api/games',json={'title':'New game'}).json()
    path = '/api/games/'+snapshot['id']
    assert client.get(path+'/export').status_code == 400
    doc = copy.deepcopy(snapshot['document'])
    doc['rounds'] = [question()]
    saved = client.put(path,json={'document':doc,'revision':snapshot['revision']})
    assert saved.status_code == 200
    assert client.put(path,json={'document':doc,'revision':snapshot['revision']}).status_code == 409
    assert client.post(path+'/publish',json={'revision':saved.json()['revision']}).status_code == 200
    assert client.get(path+'/export').headers['content-type'] == 'application/zip'


def test_malformed_draft_does_not_replace_editable_document(catalog):
    snapshot = draft(catalog)
    doc = copy.deepcopy(snapshot['document'])
    doc['rounds'] = [None]
    with pytest.raises(ValueError, match='Раунды'):
        catalog.save(snapshot['id'], doc, snapshot['revision'])
    assert catalog.snapshot(snapshot['id'])['document'] == snapshot['document']


def test_export_includes_all_referenced_image_audio_video(catalog):
    snapshot = catalog.open('demo-quiz')
    media = {q['media']['file'] for q in snapshot['document']['rounds'] if q.get('media')}
    assert {q['media']['type'] for q in snapshot['document']['rounds'] if q.get('media')} == {'image','audio','video'}
    with zipfile.ZipFile(io.BytesIO(catalog.export('demo-quiz'))) as archive:
        assert set(archive.namelist()) == {'game.json'} | media
        for name in media:
            assert archive.read(name) == (catalog.drafts/'demo-quiz'/name).read_bytes()


def test_delete_draft_removes_media_and_keeps_private_recovery_archive(catalog, tmp_path):
    snapshot = draft(catalog)
    game_id = snapshot['id']
    folder = catalog.drafts/game_id
    (folder/'media').mkdir()
    (folder/'media/orphan.png').write_bytes(b'orphan media')
    assert catalog.delete(game_id,snapshot['delete_revision']) == {'ok':True}
    assert not folder.exists()
    assert game_id not in {g['id'] for g in catalog.list()}
    backup = next((catalog.data/'backups'/game_id).glob('*-deleted.zip'))
    with zipfile.ZipFile(backup) as archive:
        assert archive.read('draft/media/orphan.png') == b'orphan media'
        assert json.loads(archive.read('draft/game.json'))['title'] == 'Test game'
    recreated = Catalog(catalog.data,catalog.games,catalog.bundled)
    with pytest.raises(ValueError,match='удалена'):
        recreated.open(game_id)
    with pytest.raises(ValueError,match='удалена'):
        recreated.save(game_id,snapshot['document'],snapshot['revision'])
    with pytest.raises(ValueError,match='удалена'):
        recreated.publish(game_id,snapshot['revision'])


@pytest.mark.parametrize('override',[False,True])
def test_delete_bundled_game_does_not_fall_back_after_update(catalog, override):
    source = (catalog.bundled/'example-race/game.json').read_bytes()
    snapshot = catalog.open('example-race')
    if override:
        snapshot = catalog.publish('example-race',snapshot['revision'])
    catalog.delete('example-race',snapshot['delete_revision'])
    assert not (catalog.drafts/'example-race').exists()
    assert not (catalog.games/'example-race').exists()
    assert (catalog.bundled/'example-race/game.json').read_bytes() == source
    assert 'example-race' not in {g['id'] for g in Catalog(catalog.data,catalog.games,catalog.bundled).list()}
    roots = [catalog.games,catalog.bundled]
    assert 'library-example-race' not in {p['id'] for p in list_packs(roots)['packs']}
    assert not list_packs(roots)['errors']
    with pytest.raises(ValueError,match='удалена'):
        find_pack(roots,'library-example-race')


def test_delete_conflicts_with_other_author_or_external_publication(catalog):
    snapshot = draft(catalog)
    changed = copy.deepcopy(snapshot['document'])
    changed['title'] = 'Another author'
    saved = catalog.save(snapshot['id'],changed,snapshot['revision'])
    with pytest.raises(Conflict):
        catalog.delete(snapshot['id'],snapshot['delete_revision'])
    published = catalog.publish(snapshot['id'],saved['revision'])
    manifest = catalog.games/snapshot['id']/'game.json'
    external = copy.deepcopy(changed)
    external['title'] = 'External update'
    manifest.write_bytes(json.dumps(external).encode())
    with pytest.raises(Conflict):
        catalog.delete(snapshot['id'],published['delete_revision'])
    assert manifest.exists() and (catalog.drafts/snapshot['id']).exists()
    assert not list((catalog.data/'backups'/snapshot['id']).glob('*-deleted.zip'))


def test_delete_api_requires_author_csrf_and_fresh_revision(client,catalog):
    snapshot = draft(catalog)
    path = '/api/games/'+snapshot['id']
    body = {'revision':snapshot['delete_revision']}
    assert client.request('DELETE',path,json=body).status_code == 401
    client.post('/api/login',json={'password':'editor-password'})
    assert client.request('DELETE',path,json=body,headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.request('DELETE',path,json={'revision':'a'*64}).status_code == 409
    assert client.request('DELETE','/api/games/..',json=body).status_code in (400,404,405)
    assert client.request('DELETE',path,json=body).status_code == 200
    assert client.post(path+'/open').status_code == 400
    assert client.put(path,json={'revision':snapshot['revision'],'document':snapshot['document']}).status_code == 400


def test_invalid_package_can_be_deleted_from_library(catalog):
    snapshot = draft(catalog)
    (catalog.drafts/snapshot['id']/'game.json').write_text('{broken json',encoding='utf-8')
    item = next(g for g in catalog.list() if g['id']==snapshot['id'])
    assert item['error']
    catalog.delete(snapshot['id'],item['delete_revision'])
    assert not (catalog.drafts/snapshot['id']).exists()


def test_deleted_game_cannot_start_new_rooms_but_existing_rooms_keep_media(tmp_path,monkeypatch):
    from app import main
    catalog = Catalog(tmp_path/'builder',tmp_path/'games',ROOT/'games')
    monkeypatch.setattr(main,'store',Store(tmp_path/'game.sqlite3'))
    monkeypatch.setattr(main,'DEV_MODE',True)
    monkeypatch.setenv('GAME_PACKS_DIR',str(catalog.games))
    snapshot = catalog.open('demo-quiz')
    catalog.publish('demo-quiz',snapshot['revision'])
    snapshot = catalog.open('demo-quiz')
    with TestClient(main.app) as client:
        auth = client.post('/api/login',json={'name':'Host'}).json()
        headers = {'Authorization':'Bearer '+auth['token']}
        code = client.post('/api/rooms',headers=headers,json={'pack':'demo'}).json()['code']
        room = client.get('/api/rooms/'+code,headers=headers).json()
        media = [q['media']['url'] for q in room['question_list'] if q.get('media')]
        assert len(media)==3
        before = [client.get(url).content for url in media]
        catalog.delete('demo-quiz',snapshot['delete_revision'])
        assert not (catalog.games/'demo-quiz').exists()
        assert not (catalog.drafts/'demo-quiz').exists()
        assert 'library-demo-quiz' not in {p['id'] for p in client.get('/api/packs',headers=headers).json()['packs']}
        assert client.post('/api/rooms',headers=headers,json={'pack':'demo'}).status_code == 400
        assert client.post('/api/practice',headers=headers,json={'pack':'library-demo-quiz'}).status_code == 400
        assert client.get('/api/rooms/'+code,headers=headers).json()['question_count']==23
        assert [client.get(url).content for url in media] == before
