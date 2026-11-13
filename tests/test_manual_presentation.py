"""Host-controlled scenes, answer media and complete display preload manifests."""
import json

import pytest

from app.media_items import media_items
from app.pack_validation import publication_issues
from app.store import Store


def setup_game(tmp_path, mode='binary', kind='audio', preload=True):
    db = Store(tmp_path/'manual.sqlite3')
    host, a, b, screen = [dict(id=n, name=n) for n in ('h', 'a', 'b', 'screen')]
    stage = dict(id='s', type=mode, title='Round', chooser='host', auto_advance=True,
                 categories=['Topic'], answer_mode='all')
    q = dict(id='q', stage='s', category='Topic', text='Question', answer='Answer', value=100,
             media=dict(kind='video', url='/question.mp4', start=3, end=8), seconds=1)
    if kind:
        q['attachments'] = [dict(kind=kind, url='/answer', answer=True, start=2, end=12)]
    if mode == 'binary':
        q.update(choices=['Yes', 'No'], correct_choice=0, answer='Yes')
    code = db.create(host, stages=[stage], questions=[q, dict(q, id='next')], settings=dict(preload_media=preload))
    for user in (a, b): db.change(code, user, 'join')
    db.change(code, screen, 'watch')
    db.change(code, host, 'start'); db.change(code, host, 'next')
    if mode == 'grid': db.change(code, host, 'pick', question='q')
    return db, code, host, a, b


@pytest.mark.parametrize('mode', ['blitz', 'binary', 'grid'])
@pytest.mark.parametrize('kind', [None, 'image', 'audio', 'video'])
def test_host_reveal_starts_only_answer_files_and_grading_does_not_interrupt(tmp_path, monkeypatch, mode, kind):
    db, code, host, a, b = setup_game(tmp_path, mode, kind)
    monkeypatch.setattr('app.store.time.time', lambda: 10000000000)
    assert db.read(code)['deadline'] is None and not db.tick(code)
    for user in (a, b):
        db.change(code, user, 'answer', **(dict(choice=0) if mode == 'binary' else dict(text='Answer')))
    if mode == 'binary':
        assert db.read(code)['phase'] == 'question'
        assert all(p['score'] == 0 for p in db.read(code)['players'])
    screen = db.public(code, 'screen', display=True)
    assert 'answer' not in screen['question']
    assert [m['url'] for m in media_items(screen['question'])] == ['/question.mp4']
    with pytest.raises(ValueError): db.change(code, a, 'display_answer')
    db.change(code, host, 'display_answer')
    state = db.read(code)
    assert state['display_scene'] == 'answer' and state['advance_at'] is None
    assert not db.public(code, 'b')['can_answer']
    playback = state['media_playback']
    if kind in ('audio', 'video'):
        assert playback['playing'] and playback['mode'] == 'full'
    else:
        assert playback is None
    if mode != 'binary':
        # Displaying the answer does not grade free text on the host's behalf.
        assert db.public(code, 'a')['question']['answer'] == 'Answer'
        db.change(code, host, 'correct', player='a'); db.change(code, host, 'wrong', player='b')
        assert db.read(code)['media_playback'] == playback
    screen = db.public(code, 'screen', display=True)
    assert screen['question']['answer'] == ('Yes' if mode == 'binary' else 'Answer')
    assert [m['url'] for m in media_items(screen['question'])] == (['/answer'] if kind else [])
    answers = db.read(code)['answers']
    db.change(code, host, 'display_question')
    assert not db.read(code)['media_playback']['playing']
    assert 'answer' not in db.public(code, 'screen', display=True)['question']
    db.change(code, host, 'display_answer')
    assert db.read(code)['answers'] == answers
    assert not db.tick(code)
    assert Store(db.path).read(code)['active'] == 'q'
    db.change(code, host, 'next')


@pytest.mark.parametrize('enabled', [False, True])
def test_preload_manifest_contains_all_unique_files_only_on_display(tmp_path, enabled):
    db, code, host, a, b = setup_game(tmp_path, preload=enabled)
    assert db.public(code, 'screen', display=True)['media_manifest'] == (['/question.mp4', '/answer'] if enabled else [])
    for uid in ('h', 'a', 'b'):
        assert db.public(code, uid)['media_manifest'] == []
    assert Store(db.path).read(code)['settings']['preload_media'] is enabled


@pytest.mark.parametrize('value', ['true', 1, None])
def test_preload_setting_requires_a_boolean(value):
    doc = dict(title='Game', settings=dict(preload_media=value), rounds=[])
    assert any(i['field'] == 'settings.preload_media' for i in publication_issues(doc))


def test_existing_room_deadline_is_removed_without_revealing_answer(tmp_path):
    db, code, host, a, b = setup_game(tmp_path)
    state = db.read(code); state.update(deadline=1, advance_at=2, time_expired=True)
    with db.connect() as connection:
        connection.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(state), code))
    assert db.public(code, 'a')['can_answer']
    assert not db.tick(code)
    assert db.read(code)['deadline'] is None
    assert db.read(code)['display_scene'] == 'question'


def test_multiple_answer_files_keep_the_longer_shared_timeline(tmp_path, monkeypatch):
    from app.store import media_position
    db, code, host, a, b = setup_game(tmp_path)
    state=db.read(code)
    state['pack'][0]['attachments']=[dict(kind='audio',url='/short',start=0,end=2,answer=True),
                                    dict(kind='video',url='/long',start=0,end=6,answer=True)]
    with db.connect() as connection:
        connection.execute('UPDATE rooms SET state=? WHERE code=?',(json.dumps(state),code))
    now=[1000.];monkeypatch.setattr('app.store.time.time',lambda:now[0])
    db.change(code,host,'display_answer');now[0]+=4
    assert media_position(db.read(code),now[0])==4
    db.change(code,host,'media_pause',question='q')
    assert db.read(code)['media_playback']['position']==4


@pytest.mark.parametrize('kind', [None, 'image', 'audio', 'video'])
@pytest.mark.parametrize('legacy', [False, True])
def test_grid_answer_payload_excludes_question_text_and_media(tmp_path, kind, legacy):
    db, code, host, a, b = setup_game(tmp_path, mode='grid', kind=kind)
    db.change(code, host, 'display_answer')
    if legacy:
        state = db.read(code); state.pop('display_scene')
        with db.connect() as connection:
            connection.execute('UPDATE rooms SET state=? WHERE code=?', (json.dumps(state), code))
    answer = db.public(code, 'screen', display=True)
    assert answer['display_scene'] == 'answer'
    assert answer['question']['text'] == ''
    assert answer['question']['answer'] == 'Answer'
    assert [m['url'] for m in media_items(answer['question'])] == (['/answer'] if kind else [])
    assert db.public(code, 'h')['question']['text'] == 'Question'
    db.change(code, host, 'display_question')
    question = db.public(code, 'screen', display=True)['question']
    assert question['text'] == 'Question' and 'answer' not in question
    assert [m['url'] for m in media_items(question)] == ['/question.mp4']
