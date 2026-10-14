import copy
import io
import json
from pathlib import Path
import zipfile

import pytest

from app.packs import load_pack, materialize_pack
from app.pack_validation import publication_issues
from builder.store import Catalog

ROOT=Path(__file__).resolve().parents[1]


def test_video_audio_only_survives_save_publish_export_and_room_materialization(tmp_path):
    catalog=Catalog(tmp_path/'builder',tmp_path/'games',tmp_path/'bundled')
    draft=catalog.create('Hidden video')
    asset=catalog.upload(draft['id'],ROOT/'static/demo/colors.mp4','video')
    doc=copy.deepcopy(draft['document'])
    doc['rounds']=[dict(id='q1',type='question',text='Song?',answer='Yes',points=100,time_limit=45,
                        media=dict(type='video',file=asset['file'],audio_only=True,start=.2,end=1.2))]
    draft=catalog.save(draft['id'],doc,draft['revision'])
    assert draft['document']['rounds'][0]['media']['audio_only'] is True
    catalog.publish(draft['id'],draft['revision'])
    pack=load_pack(catalog.published_folder(draft['id']))
    assert pack['questions'][0]['media']['kind']=='video' and pack['questions'][0]['media']['audio_only']
    assets=materialize_pack(pack,tmp_path/'room-media')
    assert assets[0]['kind']=='video' and pack['questions'][0]['media']['audio_only']
    assert pack['questions'][0]['media']['url'].startswith('/api/media/')
    exported=catalog.export(draft['id'])
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        assert json.loads(archive.read('game.json'))['rounds'][0]['media']['audio_only'] is True


@pytest.mark.parametrize('kind,value',[('video','yes'),('video',1),('audio',True),('image',True)])
def test_audio_only_flag_has_clear_field_validation(kind,value):
    doc=dict(title='Game',rounds=[dict(id='q',type='question',text='?',answer='Yes',media=dict(type=kind,file='file',audio_only=value))])
    assert any(i['field']=='media.audio_only' for i in publication_issues(doc))
