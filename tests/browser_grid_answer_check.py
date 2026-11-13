"""Run directly: verify grid answer scenes in Chromium with real media and CSS."""
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.packs import materialize_pack
from app.store import Store
from playwright.sync_api import expect, sync_playwright


def main():
    folder = ROOT/'data'/('grid-answer-browser-'+uuid4().hex)
    folder.mkdir(parents=True)
    db = Store(folder/'game.sqlite3')
    host, player = dict(id='dev-grid-host', name='Host'), dict(id='dev-grid-player', name='Player')
    pack = dict(questions=[])
    files = dict(image='games/example-race/media/red.png', audio='static/demo/signals.wav', video='static/demo/colors.mp4')
    for kind in ('text', 'image', 'audio', 'video'):
        q = dict(id=kind, stage='g', category='Topic', text='Question '+kind, answer='Answer '+kind, value=100,
                 media=dict(kind='image', source=str(ROOT/'games/demo-quiz/media/triangle.png')))
        if kind != 'text':
            q['attachments'] = [dict(kind=kind, source=str(ROOT/files[kind]), answer=True)]
        pack['questions'].append(q)
    assets = materialize_pack(pack, folder/'media')
    code = db.create(host, questions=pack['questions'], assets=assets,
                     stages=[dict(id='g', type='grid', title='Grid', categories=['Topic'], chooser='host', auto_advance=False)])
    db.change(code, player, 'join')
    token = db.session(host)
    base = 'http://127.0.0.1:8139'
    env = {**os.environ, 'DEV_MODE':'true', 'DATABASE_PATH':str(folder/'game.sqlite3'), 'APP_URL':base}
    with (folder/'server.log').open('w', encoding='utf8') as log:
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8139'],
                                  cwd=ROOT, env=env, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
                context = browser.new_context(viewport=dict(width=1280, height=800))
                page = context.new_page(); errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for _ in range(60):
                    try:
                        if context.request.get(base+'/api/config').ok: break
                    except Exception: pass
                    time.sleep(.2)
                page.goto(base+'/display?room='+code)
                page.wait_for_function('room?.display && mediaCache.urls.size === 4 && !mediaCache.pending.size')
                def action(name, **fields):
                    response = context.request.post(base+'/api/rooms/'+code+'/action',
                        headers={'Authorization':'Bearer '+token}, data=dict(action=name, **fields))
                    assert response.ok, response.text()
                action('start'); action('next')
                for kind in ('text', 'image', 'audio', 'video'):
                    action('pick', question=kind)
                    expect(page.locator('#question-text')).to_have_text('Question '+kind)
                    expect(page.locator('#question-text')).to_be_visible()
                    for _ in range(2):
                        action('display_answer')
                        expect(page.locator('#solution')).to_have_text('Правильный ответ: Answer '+kind)
                        expect(page.locator('#solution')).to_be_visible()
                        expect(page.locator('#question-text')).to_be_hidden()
                        assert page.locator('#question-text').text_content() == ''
                        assert page.evaluate('room.question.text') == ''
                        rendered = page.locator('#media-content img, #media-content audio, #media-content video')
                        assert rendered.count() == (0 if kind == 'text' else 1)
                        if kind != 'text':
                            assert rendered.first.evaluate('(node)=>node.src') == page.evaluate('mediaSource(room.question.attachments[0].url)')
                        if kind in ('audio', 'video'):
                            page.wait_for_function('(kind)=>document.querySelector("#media-content "+kind).currentTime>0', arg=kind)
                        page.screenshot(path=str(folder/(kind+'-answer.png')))
                        action('display_question')
                        expect(page.locator('#question-text')).to_have_text('Question '+kind)
                        expect(page.locator('#question-text')).to_be_visible()
                        expect(page.locator('#solution')).to_be_hidden()
                    if kind != 'video': action('next')
                assert not errors, errors
                browser.close()
            print('PASS: grid text, image, audio and video answers show no question text or question media; returning to question restores it.')
            print('Artifacts:', folder)
        finally:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=10)


if __name__ == '__main__': main()
