"""Exercise real player/display screens through all competitive game modes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.store import Store
from playwright.sync_api import expect, sync_playwright


def main():
    folder = Path(tempfile.mkdtemp(prefix='tg-game-browser-audit-'))
    artifacts = ROOT/'data'/('logic-browser-'+uuid4().hex)
    artifacts.mkdir(parents=True)
    db = Store(folder/'game.sqlite3')
    host = dict(id='dev-audit-host', name='Host')
    token = db.session(host)
    base = 'http://127.0.0.1:8140'
    env = {**os.environ, 'DEV_MODE':'true', 'DATABASE_PATH':str(folder/'game.sqlite3'), 'APP_URL':base}
    with (artifacts/'server.log').open('w', encoding='utf8') as log:
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8140'],
                                  cwd=ROOT, env=env, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                api = browser.new_context()
                for _ in range(60):
                    try:
                        if api.request.get(base+'/api/config').ok: break
                    except Exception: pass
                    time.sleep(.2)
                errors = []
                for mode in ('blitz', 'grid-all', 'grid-single', 'binary'):
                    a = api.request.post(base+'/api/login', data=dict(name='A '+mode)).json()
                    b = api.request.post(base+'/api/login', data=dict(name='B '+mode)).json()
                    kind = 'grid' if mode.startswith('grid') else mode
                    stage = dict(id='s', type=kind, title=mode, categories=['Topic'], chooser='winner',
                                 answer_mode='single' if mode == 'grid-single' else 'all', auto_advance=False)
                    q = dict(id='q1', stage='s', category='Topic', text='Question '+mode, answer='Yes', value=100)
                    if mode == 'binary': q.update(choices=['Yes', 'No'], correct_choice=0)
                    code = db.create(host, stages=[stage], questions=[q, dict(q, id='q2')])
                    for auth in (a, b): db.change(code, auth['user'], 'join')
                    path = base+'/api/rooms/'+code+'/action'
                    def action(name, auth=None, **fields):
                        response = api.request.post(path, headers={'Authorization':'Bearer '+(auth['token'] if auth else token)},
                                                    data=dict(action=name, **fields))
                        assert response.ok, response.text()
                        return response.json()
                    ctx = browser.new_context(viewport=dict(width=390, height=844))
                    ctx.add_init_script('sessionStorage.setItem("auth", '+json.dumps(json.dumps(a))+')')
                    player = ctx.new_page(); player.on('pageerror', lambda error: errors.append(str(error)))
                    player.goto(base+'/?room='+code)
                    player.wait_for_function('room?.phase === "lobby"')
                    screen_ctx = browser.new_context(viewport=dict(width=1280, height=800))
                    screen = screen_ctx.new_page(); screen.on('pageerror', lambda error: errors.append(str(error)))
                    screen.goto(base+'/display?room='+code)
                    screen.wait_for_function('room?.display === true')
                    action('start'); action('next')
                    if kind == 'grid': action('pick', question='q1')
                    expect(player.locator('#question-text')).to_be_visible()
                    if mode == 'grid-single': player.locator('#buzz-answer').click()
                    if mode == 'binary': player.locator('[data-choice="0"]').click()
                    else:
                        player.locator('#answer-text').fill('Yes'); player.locator('#answer-send').click()
                    if mode == 'grid-single':
                        player.wait_for_function('room?.phase === "review"')
                        action('display_answer'); action('wrong', player=a['user']['id'])
                        assert not db.public(code, b['user']['id'])['can_buzz']
                    else:
                        action('answer', auth=b, **(dict(choice=1, question='q1') if mode == 'binary' else dict(text='No', question='q1')))
                        if mode == 'binary':
                            assert db.read(code)['phase'] == 'question'
                            action('close')
                        else:
                            action('correct', player=a['user']['id']); action('wrong', player=b['user']['id'])
                        player.wait_for_function('room?.phase === "reveal"')
                        assert player.evaluate('room.question.answer === undefined && room.question.correct_choice === undefined')
                        expect(player.locator('#solution')).to_be_hidden()
                        action('display_answer')
                    expect(player.locator('#solution')).to_be_visible()
                    expect(player.locator('#question-text')).to_be_hidden()
                    expect(screen.locator('#question-text')).to_be_hidden()
                    action('pause'); expect(player.locator('#pause-panel')).to_be_visible()
                    action('unpause'); expect(player.locator('#solution')).to_be_visible()
                    screen.reload(); expect(screen.locator('#solution')).to_be_visible()
                    action('display_question'); expect(player.locator('#question-text')).to_be_visible()
                    expect(player.locator('#solution')).to_be_hidden()
                    if kind == 'grid':
                        action('display_board')
                        if mode == 'grid-all':
                            expect(player.locator('#question-board')).to_be_visible()
                            player.locator('[data-pick="q2"]').click()
                        else: action('pick', question='q2')
                    else: action('next')
                    player.wait_for_function('room?.active === "q2" && room.phase === "question"')
                    action('close'); action('display_answer'); action('end_round'); action('show_scores')
                    expect(screen.locator('#round-scores')).to_be_visible()
                    action('next'); expect(player.locator('#finished')).to_be_visible()
                    player.screenshot(path=str(artifacts/(mode+'-finished.png')))
                    ctx.close(); screen_ctx.close()
                    print('PASS:', mode, flush=True)
                assert not errors, errors
                browser.close()
            print('PASS: player, host and display transitions; pause, reconnect, answer privacy, grid selection and final results.')
            print('Artifacts:', artifacts)
        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=10)


if __name__ == '__main__': main()
