"""Exercise real Chromium UI against isolated game and builder servers."""
from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from builder.auth import hash_password

ARTIFACTS = ROOT/'data/browser-check'
PASSWORD = 'browser-check-only-password'


@contextmanager
def server(module, env, log):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    with log.open('w', encoding='utf-8') as stream:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', module, '--host', '127.0.0.1',
                                    '--port', str(port)], cwd=ROOT, env=env, stdout=stream, stderr=stream)
        try:
            for _ in range(100):
                try:
                    if httpx.get(url+'/api/health', timeout=1).is_success:
                        break
                except httpx.HTTPError:
                    pass
                if process.poll() is not None:
                    raise RuntimeError('Test server failed: '+log.read_text())
                time.sleep(.1)
            else:
                raise RuntimeError('Test server did not start')
            yield url
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill();process.wait()


def screenshot(page, name):
    page.screenshot(path=ARTIFACTS/(name+'.png'), full_page=True)


def check_builder(page, url):
    page.goto(url)
    page.get_by_label('Пароль конструктора', exact=True).fill(PASSWORD)
    page.get_by_role('button', name='Войти в мастерскую').click()
    page.get_by_role('button', name='+ Новая игра', exact=True).click()
    page.get_by_label('Название игры', exact=True).fill('Проверка UI 0.0.5')
    page.get_by_role('button', name='Создать игру →', exact=True).click()
    expect(page.locator('#editor-title')).to_have_text('Проверка UI 0.0.5')
    page.get_by_role('tab', name='Настройки игры', exact=True).click()
    page.locator('#game-time-limit').fill('120')
    page.locator('#game-points').fill('200')
    expect(page.locator('#app-version')).to_contain_text('0.0.5 build ')
    screenshot(page, 'builder-settings-desktop')
    page.set_viewport_size(dict(width=390, height=844))
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Mobile editor overflows'
    screenshot(page, 'builder-settings-mobile')
    page.set_viewport_size(dict(width=1440, height=1000))
    page.get_by_role('tab', name='Раунды', exact=True).click()
    page.get_by_role('button', name='+ Вопрос', exact=True).click()
    page.locator('#question-text').fill('Сколько будет 2 + 2?')
    page.locator('#answer').fill('4')
    page.locator('#material-panel > summary').click()
    page.locator('#media-type').select_option('audio')
    page.locator('#media-file').set_input_files(str(ROOT/'static/demo/signals.wav'))
    expect(page.locator('#attached-file')).to_be_visible()
    expect(page.locator('#clip-duration')).to_contain_text('Запись')
    page.locator('#clip-start').fill('00:01')
    page.locator('#clip-end').fill('00:02')
    page.locator('#preview-panel > summary').click()
    expect(page.locator('#preview-content')).to_contain_text('200 очков · 120 сек.')
    page.locator('#add-question').click()
    page.locator('#question-text').fill('Сколько будет 3 + 3?')
    page.locator('#answer').fill('6')

    page.locator('#add-stage-panel > summary').click()
    page.locator('#new-stage-type').select_option('grid')
    page.locator('#add-stage').click()
    page.get_by_role('tab', name='Категории', exact=True).click()
    for name in ('Космос', 'География'):
        page.locator('#new-category').fill(name)
        page.locator('#add-category').click()
    page.get_by_role('tab', name='Вопросы', exact=True).click()
    page.locator('#question-text').fill('Вопрос удаляемой категории')
    page.locator('#answer').fill('Удаляемый ответ')
    page.locator('#grid-category').select_option('Космос')
    page.locator('#add-question').click()
    page.locator('#question-text').fill('Столица Италии?')
    page.locator('#answer').fill('Рим')
    page.locator('#points').fill('1000')
    page.locator('#grid-category').select_option('География')
    page.get_by_role('tab', name='Категории', exact=True).click()
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.locator('[data-category-remove="0"]').click()
    expect(page.locator('[data-category-name]')).to_have_count(2)
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('[data-category-remove="0"]').click()
    expect(page.locator('[data-category-name]')).to_have_count(1)
    page.get_by_role('tab', name='Вопросы', exact=True).click()
    expect(page.locator('#round-list button')).to_have_count(1)
    expect(page.locator('#question-text')).to_have_value('Столица Италии?')

    page.locator('#add-stage-panel > summary').click()
    page.locator('#new-stage-type').select_option('binary')
    page.locator('#add-stage').click()
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#stage-delete').click()
    expect(page.locator('#stage-list button')).to_have_count(2)
    page.locator('#save').click()
    expect(page.locator('#save-status')).to_have_text('Черновик сохранён')
    page.locator('#publish').click()
    expect(page.locator('#notice-text')).to_contain_text('Игра опубликована')
    page.reload()
    expect(page.locator('#editor-title')).to_have_text('Проверка UI 0.0.5')
    screenshot(page, 'builder-round-desktop')
    games = page.request.get(url+'/api/games').json()
    return next(game['id'] for game in games if game['title'] == 'Проверка UI 0.0.5')


def login(page, url, name):
    page.goto(url)
    page.locator('#name').fill(name)
    page.locator('#login-form button').click()
    expect(page.locator('#home')).to_be_visible()


def check_display(browser, stack, app_url, game_id, watch):
    host_context = stack.enter_context(browser.new_context(viewport=dict(width=1440, height=1000)))
    player_context = stack.enter_context(browser.new_context(viewport=dict(width=390, height=844)))
    screen_context = stack.enter_context(browser.new_context(viewport=dict(width=1440, height=1000)))
    host, player, screen = host_context.new_page(), player_context.new_page(), screen_context.new_page()
    for page in (host, player, screen):
        watch(page)
    login(host, app_url, 'QA Host')
    host.get_by_role('button', name='Ведущий', exact=True).click()
    host.locator('#pack').select_option('library-'+game_id)
    host.locator('#create').click()
    expect(host.locator('#room-code')).not_to_be_empty()
    code = host.locator('#room-code').inner_text().strip()
    login(player, app_url, 'QA Player')
    player.locator('#code').fill(code)
    player.locator('#join-submit').click()
    expect(player.locator('#game')).to_be_visible()
    screen.goto(app_url+'/display?room='+code)
    expect(screen.locator('#display-preview')).to_be_visible()
    expect(screen.locator('#app-version')).to_contain_text('0.0.5 build ')
    screenshot(screen, 'display-lobby')
    host.locator('#start').click()
    expect(screen.locator('#grid-intro')).to_be_visible()
    host.locator('#skip-intro').click()
    expect(screen.locator('#question-text')).to_have_text('Сколько будет 2 + 2?')
    expect(screen.locator('#question')).to_be_visible()
    expect(screen.locator('#media-content audio')).to_have_count(1)
    expect(screen.locator('#media-content .clip-player')).to_be_visible()
    expect(screen.get_by_role('slider', name='Позиция в отрывке')).to_have_attribute('max', '1')
    expect(player.locator('#media-content audio')).to_have_count(0)
    screenshot(screen, 'display-question')
    host.locator('#pause-game').click()
    expect(screen.locator('#pause-panel')).to_be_visible()
    host.locator('#display-game-scores').click()
    expect(screen.locator('#presentation-scores')).to_be_visible()
    host.locator('#continue-game').click()
    expect(screen.locator('#question')).to_be_visible()
    player.locator('#answer-text').fill('4')
    player.locator('#answer-send').click()
    host.locator('button[data-verdict="correct"]').click()
    expect(screen.locator('#solution')).to_contain_text('4')
    screenshot(screen, 'display-answer')
    host.locator('#next').click()
    expect(screen.locator('#question-text')).to_have_text('Сколько будет 3 + 3?')
    player.locator('#answer-text').fill('6')
    player.locator('#answer-send').click()
    host.locator('button[data-verdict="correct"]').click()
    host.locator('#round-next').click()
    expect(screen.locator('#grid-intro')).to_be_visible()
    host.locator('#skip-intro').click()
    expect(screen.locator('#question-board')).to_be_visible()
    screenshot(screen, 'display-grid')
    host.locator('[data-pick]').click()
    expect(screen.locator('#question-text')).to_have_text('Столица Италии?')
    player.locator('#answer-text').fill('Рим')
    player.locator('#answer-send').click()
    host.locator('button[data-verdict="correct"]').click()
    host.locator('#round-results-button').click()
    expect(screen.locator('#round-scores')).to_be_visible()
    expect(screen.locator('#round-results')).to_contain_text('1400')
    screenshot(screen, 'display-results')
    assert player.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Player UI overflows'


def main():
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    errors = []
    pages = []
    def watch(page):
        pages.append(page)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('response', lambda response: errors.append(f'HTTP {response.status}: {response.url}') if response.status >= 500 else None)
    with tempfile.TemporaryDirectory(prefix='rat-race-browser-') as temporary, ExitStack() as stack:
        folder = Path(temporary)
        env = dict(os.environ, DEV_MODE='true', BOT_TOKEN='', DATABASE_PATH=str(folder/'game.sqlite3'),
                   BUILDER_DATA_DIR=str(folder/'builder'), GAME_PACKS_DIR=str(folder/'games'),
                   BUILDER_PASSWORD_HASH=hash_password(PASSWORD))
        game = stack.enter_context(server('app.main:app', env, ARTIFACTS/'app.log'))
        builder = stack.enter_context(server('builder.main:app', env, ARTIFACTS/'builder.log'))
        playwright = stack.enter_context(sync_playwright())
        browser = stack.enter_context(playwright.chromium.launch())
        try:
            context = stack.enter_context(browser.new_context(viewport=dict(width=1440, height=1000)))
            page = context.new_page();watch(page)
            game_id = check_builder(page, builder)
            check_display(browser, stack, game, game_id, watch)
            assert not errors, '\n'.join(errors)
        except Exception:
            for index, page in enumerate(pages):
                if not page.is_closed():
                    screenshot(page, 'failure-'+str(index))
            raise
        finally:
            (ARTIFACTS/'browser-errors.txt').write_text('\n'.join(errors), encoding='utf-8')
    print('Real Chromium checks passed: builder, mobile layout, display, answers, pause and scores.')


if __name__ == '__main__':
    main()
