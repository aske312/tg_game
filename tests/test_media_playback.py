import pytest
from fastapi.testclient import TestClient

from app.store import Store, media_position


@pytest.fixture
def media_game(tmp_path, monkeypatch):
    now=[1000.]
    monkeypatch.setattr('app.store.time.time',lambda:now[0])
    db=Store(tmp_path/'media.sqlite3')
    host,player=dict(id='host',name='Host'),dict(id='player',name='Player')
    questions=[dict(id='audio',text='?',answer='Yes',value=100,seconds=3600,media=dict(kind='audio',url='/audio.wav',start=20,end=50)),
               dict(id='image',text='?',answer='Yes',value=100,seconds=3600,media=dict(kind='image',url='/image.png')),
               dict(id='video',text='?',answer='Yes',value=100,seconds=3600,media=dict(kind='video',url='/video.mp4',start=5))]
    code=db.create(host,questions=questions)
    db.change(code,player,'join');db.change(code,host,'start')
    return db,code,host,player,now


def test_autoplay_pause_resume_and_position_persist(media_game):
    db,code,host,player,now=media_game
    playback=db.read(code)['media_playback']
    assert playback['playing'] and playback['question']=='audio' and playback['position']==0
    now[0]+=5
    db.change(code,host,'media_pause',question='audio')
    assert db.read(code)['media_playback']['position']==5
    now[0]+=80
    db=Store(db.path)
    assert media_position(db.read(code),now[0])==5
    db.change(code,host,'media_play',question='audio')
    assert db.read(code)['media_playback']['playing']
    now[0]+=3
    assert media_position(db.read(code),now[0])==8
    db.change(code,host,'media_seek',question='audio',position=12)
    assert db.read(code)['media_playback']['position']==12


def test_game_pause_freezes_media_and_round_scores_stop_it(media_game):
    db,code,host,player,now=media_game
    now[0]+=6
    db.change(code,host,'pause')
    now[0]+=100
    assert media_position(db.read(code),now[0])==6
    with pytest.raises(ValueError):db.change(code,host,'media_play',question='audio')
    db.change(code,host,'unpause')
    now[0]+=2
    assert media_position(db.read(code),now[0])==8
    db.change(code,host,'media_pause',question='audio')
    db.change(code,host,'pause');now[0]+=100;db.change(code,host,'unpause')
    assert not db.read(code)['media_playback']['playing']
    db.change(code,host,'skip_stage')
    assert db.read(code)['phase']=='finished' and db.read(code)['media_playback'] is None


def test_media_resets_between_questions_and_replays_at_end(media_game):
    db,code,host,player,now=media_game
    now[0]+=60
    db.change(code,host,'media_play',question='audio')
    assert db.read(code)['media_playback']['position']==0
    db.change(code,host,'close');db.change(code,host,'next')
    assert db.read(code)['media_playback'] is None
    with pytest.raises(ValueError):db.change(code,host,'media_play',question='image')
    db.change(code,host,'close');db.change(code,host,'next')
    db.change(code,host,'media_pause',question='video',position=18,duration=18)
    db.change(code,host,'media_play',question='video')
    assert db.read(code)['media_playback']['position']==0
    assert db.read(code)['media_playback']['duration']==18
    db.change(code,host,'close');db.change(code,host,'show_scores')
    assert not db.read(code)['media_playback']['playing']


def test_actual_file_end_can_shorten_configured_excerpt(media_game):
    db,code,host,player,now=media_game
    db.change(code,host,'media_pause',question='audio',position=18,duration=18)
    db.change(code,host,'media_play',question='audio')
    assert db.read(code)['media_playback']['position']==0


@pytest.mark.parametrize('body', [dict(question='old'),dict(question='audio',position=-1),dict(question='audio',position=float('inf')),dict(question='audio',duration=0)])
def test_invalid_or_stale_media_commands_are_atomic(media_game,body):
    db,code,host,player,now=media_game
    before=db.read(code)
    with pytest.raises(ValueError):db.change(code,host,'media_play',**body)
    assert db.read(code)==before


def test_players_and_other_room_screens_cannot_control_media(media_game):
    db,code,host,player,now=media_game
    with pytest.raises(ValueError):db.change(code,player,'media_pause',question='audio')
    other_screen=dict(id='screen',name='Screen',role='display',room='OTHER')
    db.change(code,other_screen,'watch')
    with pytest.raises(ValueError):db.change(code,other_screen,'media_pause',question='audio')
    with pytest.raises(ValueError):db.change(code,host,'media_seek',question='audio')


def test_host_commands_and_scoped_screen_controls_broadcast(media_game,monkeypatch):
    from app import main
    db,code,host,player,now=media_game
    monkeypatch.setattr(main,'store',db);monkeypatch.setattr(main,'DEV_MODE',False);monkeypatch.setattr(main,'connections',{})
    host_headers={'Authorization':'Bearer '+db.session(host)}
    with TestClient(main.app) as client:
        guest=client.post('/api/display',json=dict(code=code)).json()
        screen_headers={'Authorization':'Bearer '+guest['token']}
        with client.websocket_connect('/ws/'+code) as ws:
            ws.send_json(dict(token=guest['token']))
            assert ws.receive_json()['media_playback']['playing']
            now[0]+=4
            result=client.post('/api/rooms/'+code+'/action',headers=host_headers,json=dict(action='media_pause',question='audio'))
            assert result.status_code==200
            state=ws.receive_json();assert state['media_playback']['position']==4 and not state['media_playback']['playing']
            result=client.post('/api/display/media',headers=screen_headers,json=dict(action='media_play',question='audio',position=4,duration=30))
            assert result.status_code==200 and result.json()['display']
            assert ws.receive_json()['media_playback']['playing']
        assert client.post('/api/display/media',headers=screen_headers,json=dict(action='next',question='audio')).status_code==422
        assert client.post('/api/display/media',headers=host_headers,json=dict(action='media_pause',question='audio')).status_code==401
        assert client.post('/api/rooms/'+code+'/action',headers=screen_headers,json=dict(action='media_pause',question='audio')).status_code==401
        assert client.post('/api/display/media',headers=screen_headers,json=dict(action='media_play',question='old')).status_code==400
