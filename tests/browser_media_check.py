"""Media editor regression checks in Chromium, Firefox and WebKit.

Run: python tests/browser_media_check.py
Uses disposable local data only.
"""
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright, expect
from browser_check import server, ROOT, PASSWORD, ARTIFACTS, hash_password


def check(page, url, allow_unsupported=False):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(url)
    page.get_by_label('Пароль конструктора', exact=True).fill(PASSWORD)
    page.get_by_role('button', name='Войти в мастерскую').click()
    page.get_by_role('button', name='+ Новая игра', exact=True).click()
    page.get_by_label('Название игры', exact=True).fill('Media stress check')
    page.get_by_role('button', name='Создать игру →', exact=True).click()
    page.get_by_role('tab', name='Раунды', exact=True).click()
    page.locator('#add-question').click()
    expect(page.locator('#question-text')).to_be_visible()
    page.locator('#material-panel > summary').click()
    page.locator('#media-type').select_option('audio')
    page.locator('#media-file').set_input_files(str(ROOT/'static/demo/signals.wav'))
    page.wait_for_function("clipEditor.duration > 0 || document.getElementById('clip-player')?.error")
    if allow_unsupported and page.evaluate("!!document.getElementById('clip-player').error"):
        expect(page.locator('#clip-start-range')).to_be_disabled()
        for i in range(40):
            page.locator('#question-text').fill(f'Editing after decode failure {i}')
        page.locator('#add-question').click()
        expect(page.locator('#question-text')).to_be_editable()
        assert not errors, '\n'.join(errors)
        return 'decode error stays local; editor remains usable (playback unavailable)'
    page.locator('#preview-panel > summary').click()
    page.wait_for_function("document.querySelector('#preview-media audio')?.readyState >= 1")
    page.evaluate("""() => {
        window.originalClip = document.getElementById('clip-player');
        window.originalPreview = document.querySelector('#preview-media audio');
        window.listChanges = 0;
        window.listObserver = new MutationObserver(records => listChanges += records.length);
        listObserver.observe(document.getElementById('round-list'), {childList:true,subtree:true});
        for(let i=0;i<500;i++){
            const start=document.getElementById('clip-start-range');
            start.value=(i%10)/10;
            start.dispatchEvent(new Event('input',{bubbles:true}));
            const end=document.getElementById('clip-end-range');
            end.value=1+(i%10)/10;
            end.dispatchEvent(new Event('input',{bubbles:true}));
        }
    }""")
    assert page.evaluate('listChanges') == 0, 'Dragging rebuilt the question list'
    page.evaluate('listObserver.disconnect()')
    for i in range(40):
        page.locator('#question-text').fill(f'Editing audio question {i}')
    assert page.evaluate("originalClip === document.getElementById('clip-player')")
    assert page.evaluate("originalPreview === document.querySelector('#preview-media audio')")
    # Exercise the browser's native seek pipeline as well as our clip sliders.
    for i in range(20):
        page.evaluate('(time) => originalClip.currentTime = time', (i % 10)/10)
        page.wait_for_function('!originalClip.seeking')
    page.evaluate("commitClip(0.2,0.7)")
    page.evaluate('originalPreview.play()')
    page.wait_for_function('originalPreview.paused && originalPreview.currentTime >= 0.7')
    # Hold a video request to inspect the UI throughout a slow upload.
    pending = []
    page.route('**/api/games/*/media?kind=video', lambda route: pending.append(route))
    page.locator('#media-type').select_option('video')
    page.locator('#media-file').set_input_files(str(ROOT/'static/demo/colors.mp4'))
    expect(page.locator('#media-upload')).to_be_visible()
    expect(page.locator('#media-file')).to_be_disabled()
    page.screenshot(path=ARTIFACTS/'video-upload-pending.png', full_page=True)
    page.wait_for_function("document.getElementById('media-fields').getAttribute('aria-busy') === 'true'")
    assert page.evaluate('1 + 1') == 2, 'Upload blocked the page event loop'
    assert pending
    pending.pop().fulfill(status=400, content_type='application/json', body='{"detail":"Test upload failure"}')
    expect(page.locator('#media-upload')).to_be_hidden()
    expect(page.locator('#media-file')).to_be_enabled()
    expect(page.locator('#notice')).to_contain_text('Test upload failure')
    # Retry without reloading or losing the edited question.
    page.locator('#media-file').set_input_files(str(ROOT/'static/demo/colors.mp4'))
    expect(page.locator('#media-upload')).to_be_visible()
    assert pending
    pending.pop().continue_()
    expect(page.locator('#media-upload')).to_be_hidden()
    expect(page.locator('#media-file')).to_be_enabled()
    expect(page.locator('#question-text')).to_have_value('Editing audio question 39')
    page.unroute('**/api/games/*/media?kind=video')
    # Repeated question changes must release the old decoder and media request.
    page.locator('#add-question').click()
    assert page.evaluate("!originalClip.hasAttribute('src') && !originalPreview.hasAttribute('src')")
    for _ in range(15):
        page.locator('[data-round="0"]').click()
        page.wait_for_function('clipEditor.duration > 0')
        page.locator('[data-round="1"]').click()
    # A failed old media request must not replace the new question's preview.
    page.evaluate("originalPreview.dispatchEvent(new Event('error'))")
    expect(page.locator('#preview-content')).not_to_contain_text('Материал не найден')
    assert not errors, '\n'.join(errors)
    return 'media sliders, edits, seeks, playback and cleanup passed'


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rat-media-') as temporary, ExitStack() as stack:
        folder = Path(temporary)
        env = dict(os.environ, BUILDER_DATA_DIR=str(folder/'builder'),
                   GAME_PACKS_DIR=str(folder/'games'), BUILDER_PASSWORD_HASH=hash_password(PASSWORD))
        url = stack.enter_context(server('builder.main:app', env, ARTIFACTS/'media-builder.log'))
        playwright = stack.enter_context(sync_playwright())
        for name in os.environ.get('MEDIA_BROWSERS', 'chromium,firefox,webkit').split(','):
            with getattr(playwright, name).launch() as browser:
                page = browser.new_page()
                page.set_default_timeout(15000)
                try:
                    result = check(page, url, allow_unsupported=name == 'webkit')
                except Exception:
                    print(page.evaluate("""() => ({notice:document.getElementById('notice')?.textContent,
                        duration:document.getElementById('clip-duration')?.textContent,
                        media:[...document.querySelectorAll('audio,video')].map(p=>({
                            src:p.currentSrc,ready:p.readyState,error:p.error?.message,
                            time:p.currentTime,paused:p.paused,seeking:p.seeking,
                            ended:p.ended,muted:p.muted,network:p.networkState}))})"""), flush=True)
                    page.screenshot(path=ARTIFACTS/('media-failure-'+name+'.png'),full_page=True)
                    raise
                print(name + ': ' + result, flush=True)


if __name__ == '__main__':
    main()
