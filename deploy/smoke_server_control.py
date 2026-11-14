"""Read-only public builder admin checks using a temporary authenticated session."""
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from builder.store import Catalog
from app.version import version_info


def main():
    cfg = dotenv_values('/etc/rat-race/builder.env')
    catalog = Catalog(cfg['BUILDER_DATA_DIR'], cfg['GAME_PACKS_DIR'], Path(__file__).resolve().parents[1]/'games')
    token = catalog.session()
    try:
        with httpx.Client(base_url=cfg['BUILDER_SITE'], timeout=20) as client:
            assert client.get('/api/server').status_code == 401
            client.cookies.set('ratrace_builder', token)
            response = client.get('/api/server')
            response.raise_for_status()
            status = response.json()
            assert status['available'], status.get('message')
            expected = version_info()['build']
            for component in ('app', 'builder'):
                version = status['versions'][component]
                assert version['current']['build'] == expected, component
                assert version['previous'] and version['previous'] != version['current'], component
            assert all(value == 'active' for value in status['services'].values()), status['services']
            assert status['metrics']['cpu_percent'] is not None
            assert status['metrics']['memory']['total'] > 0
            assert status['metrics']['disk']['free'] > 0
            assert client.post('/api/server/action', json={'action': 'update'}).status_code == 403
            # Invalid requests must never reach the privileged controller.
            assert client.post('/api/server/action', headers={'X-Builder-Request': '1'},
                               json={'action': 'invalid'}).status_code == 422
            html = client.get('/').text
            assert 'app-settings' in html and 'server-settings.js' in html
            print('Builder server panel: HTTPS, authentication, CSRF, Unix socket, statistics, services and rollback targets OK.')
            print('Current versions:', {name: item['current']['version'] for name, item in status['versions'].items()})
    finally:
        catalog.logout(token)


if __name__ == '__main__':
    main()
