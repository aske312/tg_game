import copy
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.media import MAX_GAME_MEDIA_BYTES, MAX_MEDIA_BYTES
from app.packs import load_pack, materialize_pack
from builder.auth import hash_password
from builder.main import create_app
from builder.store import Catalog


def test_large_media_upload_publish_export_and_play(tmp_path, monkeypatch):
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    snapshot = catalog.create('Large media')
    source = tmp_path/'video.mp4'
    with source.open('wb') as stream:
        stream.write(b'\x00\x00\x00\x18ftypmp42')
        stream.truncate(26 * 1024 * 1024)

    # Large media must never go through Path.read_bytes, even during publication
    # and room creation. JSON manifests can still use the normal small-file API.
    original = Path.read_bytes

    def read_small(path):
        assert path.suffix not in ('.mp4', '.zip', '.part')
        return original(path)

    monkeypatch.setattr(Path, 'read_bytes', read_small)
    media = catalog.upload(snapshot['id'], source, 'video')
    assert media['size'] == source.stat().st_size
    assert catalog.upload(snapshot['id'], source, 'video') == media
    doc = copy.deepcopy(snapshot['document'])
    doc['rounds'] = [dict(id='q1', type='question', text='Question', answer='Answer',
                          media=dict(type='video', file=media['file']))]
    snapshot = catalog.save(snapshot['id'], doc, snapshot['revision'])
    catalog.publish(snapshot['id'], snapshot['revision'])
    pack = load_pack(catalog.games/snapshot['id'])
    assets = materialize_pack(pack, tmp_path/'room-media')
    assert (tmp_path/'room-media'/assets[0]['filename']).stat().st_size == media['size']
    archive = catalog.export_file(snapshot['id'])
    with zipfile.ZipFile(archive) as output:
        assert output.getinfo(media['file']).file_size == media['size']
    archive.unlink()


def test_game_quota_counts_unique_files(tmp_path, monkeypatch):
    import builder.store as store
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    game = catalog.create('Quota')['id']
    source = tmp_path/'video.mp4'
    source.write_bytes(b'\x00\x00\x00\x18ftypmp42' + bytes(100))
    monkeypatch.setattr(store, 'MAX_GAME_MEDIA_BYTES', source.stat().st_size)
    first = catalog.upload(game, source, 'video')
    assert catalog.upload(game, source, 'video') == first
    with source.open('ab') as output:
        output.write(b'x')
    with pytest.raises(ValueError, match='10'):
        catalog.upload(game, source, 'video')


def test_export_response_removes_temporary_archive(tmp_path):
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    snapshot = catalog.create('Export')
    doc = snapshot['document']
    doc['rounds'] = [dict(id='q1', type='question', text='Question', answer='Answer')]
    catalog.save(snapshot['id'], doc, snapshot['revision'])
    with TestClient(create_app(catalog, hash_password('test-password')),
                    headers={'X-Builder-Request': '1'}) as client:
        client.post('/api/login', json={'password': 'test-password'})
        response = client.get('/api/games/'+snapshot['id']+'/export')
        assert response.status_code == 200
        assert response.content.startswith(b'PK')
        assert not list((catalog.data/'exports').iterdir())
    assert MAX_MEDIA_BYTES == MAX_GAME_MEDIA_BYTES == 10 * 1024 ** 3


def test_chunked_upload_enforces_limit_and_cleans_partial_file(tmp_path, monkeypatch):
    import builder.main as main
    catalog = Catalog(tmp_path/'builder', tmp_path/'games', tmp_path/'bundled')
    game = catalog.create('Streaming')['id']
    monkeypatch.setattr(main, 'MAX_MEDIA_BYTES', 64)
    with TestClient(create_app(catalog, hash_password('test-password')),
                    headers={'X-Builder-Request': '1'}) as client:
        client.post('/api/login', json={'password': 'test-password'})
        response = client.post('/api/games/'+game+'/media?kind=video',
                               content=iter([bytes(32), bytes(33)]))
        assert response.status_code == 413
        assert not list((catalog.data/'uploads').glob('*.part'))
