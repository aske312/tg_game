"""Real builder UI; management responses are simulated, never deploy the host."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from browser_check import server
from builder.auth import hash_password
from playwright.sync_api import expect, sync_playwright


def main():
    folder = ROOT/'data/browser-check'/('server-settings-'+uuid4().hex)
    folder.mkdir(parents=True)
    env = {**os.environ, 'BUILDER_DATA_DIR': str(folder/'builder'),
           'GAME_PACKS_DIR': str(folder/'games'), 'BUILDER_PASSWORD_HASH': hash_password('browser-settings-test')}
    snapshot = dict(available=True,
                    metrics=dict(cpu_percent=12.5, cpu_count=2, memory=dict(used=1024**3, total=2*1024**3),
                                 disk=dict(used=3*1024**3, total=20*1024**3), uptime=90000),
                    versions={name: dict(current=dict(version='0.5.0', build='a'*40),
                                         previous=dict(version='0.4.0', build='b'*40)) for name in ('app', 'builder')},
                    services={unit: 'active' for unit in ('rat-race-web.service', 'rat-race-bot.service',
                                                        'rat-race-builder.service', 'rat-race-builder-proxy.service')})
    actions = []
    with server('builder.main:app', env, folder/'server.log') as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport=dict(width=1280, height=900))
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('dialog', lambda dialog: dialog.accept())
        def status(route):
            route.fulfill(json=snapshot)
        def action(route):
            actions.append(route.request.post_data_json['action'])
            snapshot['job'] = dict(id='test-job', action=actions[-1], status='running', log='Checking release...')
            route.fulfill(status=202, json={'job': snapshot['job']})
        page.route('**/api/server', status)
        page.route('**/api/server/action', action)
        page.goto(url)
        page.locator('#password').fill('browser-settings-test')
        page.locator('#login-form button').click()
        page.locator('#app-settings').click()
        dialog = page.locator('#app-settings-dialog')
        expect(dialog).to_be_visible()
        expect(page.locator('#server-stats')).to_contain_text('12.5%')
        expect(page.locator('#server-versions')).to_contain_text('0.4.0')
        expect(page.locator('#server-update')).to_be_enabled()
        page.screenshot(path=str(folder/'desktop.png'))
        page.locator('#server-update').click()
        expect(page.locator('#server-update')).to_be_disabled()
        expect(page.locator('#server-rollback')).to_be_disabled()
        assert actions == ['update']
        snapshot['job']['status'] = 'succeeded'
        page.locator('#refresh-server').click()
        expect(page.locator('#server-reload')).to_be_visible()
        page.locator('#server-rollback').click()
        expect(page.locator('#server-job-heading')).to_have_text('Откат версии')
        assert actions == ['update', 'rollback']
        page.set_viewport_size(dict(width=390, height=844))
        dialog.evaluate('(node)=>node.scrollTop=0')
        page.screenshot(path=str(folder/'mobile.png'))
        box = dialog.bounding_box()
        assert 0 <= box['x'] and box['x']+box['width'] <= 391, box
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.locator('#close-app-settings').click()
        expect(dialog).to_be_hidden()
        page.unroute('**/api/server', status)
        page.locator('#app-settings').click()
        expect(page.locator('#server-status-message')).to_contain_text('rat-race-control')
        expect(page.locator('#server-update')).to_be_disabled()
        assert not errors, errors
        browser.close()
    print('PASS: server settings, statistics, update/rollback states, reconnect fallback, desktop/mobile layout.')
    print('Artifacts:', folder)


if __name__ == '__main__':
    main()
