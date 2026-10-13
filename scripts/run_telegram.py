"""Run a local Telegram test server, HTTPS tunnel and launcher bot."""
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parent.parent


def telegram(token, method, payload=None):
    try:
        response = httpx.post(f'https://api.telegram.org/bot{token}/{method}', json=payload or {}, timeout=20)
        result = response.json()
    except (httpx.HTTPError, ValueError):
        raise RuntimeError('Cannot connect to Telegram API. Check your internet connection.') from None
    if not result.get('ok'):
        raise RuntimeError(result.get('description', 'Telegram API error'))
    return result['result']


def main():
    settings = dotenv_values(ROOT / '.env')
    token = settings.get('BOT_TOKEN', '')
    binary = ROOT / 'tools/cloudflared.exe'
    if not token:
        raise RuntimeError('Set BOT_TOKEN in .env first.')
    if not binary.exists():
        raise RuntimeError('Download tools/cloudflared.exe. See README.')
    user = telegram(token, 'getMe')
    webhook = telegram(token, 'getWebhookInfo')
    if webhook.get('url'):
        raise RuntimeError('This bot has a webhook. Use a separate test bot or disable its webhook first.')
    username = user['username']
    set_key(str(ROOT / '.env'), 'BOT_USERNAME', username)
    env = dict(os.environ)
    env.update({key: value for key, value in settings.items() if value is not None})
    env.update(DEV_MODE='false', BOT_USERNAME=username, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8')
    # Keep browser test rooms separate from Telegram rooms.
    env['DATABASE_PATH'] = str(ROOT / 'data/telegram.sqlite3')
    logdir = ROOT / 'data'
    logdir.mkdir(exist_ok=True)
    children, logs = [], []
    try:
        server_log = open(logdir / 'telegram-server.log', 'a', encoding='utf-8')
        logs.append(server_log)
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8001', '--reload', '--reload-dir', 'app'],
                                  cwd=ROOT, env=env, stdout=server_log, stderr=subprocess.STDOUT)
        children.append(server)
        for _ in range(50):
            if server.poll() is not None:
                raise RuntimeError('Server failed to start. See data/telegram-server.log (is port 8001 already in use?).')
            try:
                with httpx.Client(timeout=1) as client:
                    res = client.get('http://127.0.0.1:8001/api/config')
                    if res.status_code == 200 and res.json().get('dev_mode') is False:
                        break
            except httpx.HTTPError:
                pass
            time.sleep(.2)
        else:
            raise RuntimeError('Local server did not become ready.')

        tunnel = subprocess.Popen([str(binary), 'tunnel', '--no-autoupdate', '--protocol', 'http2', '--url', 'http://127.0.0.1:8001'],
                                  cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding='utf-8', errors='replace')
        children.append(tunnel)
        lines = queue.Queue()
        def read_tunnel():
            with open(logdir / 'tunnel.log', 'w', encoding='utf-8') as log:
                for line in tunnel.stdout:
                    log.write(line)
                    log.flush()
                    lines.put(line)
        threading.Thread(target=read_tunnel, daemon=True).start()
        deadline = time.monotonic() + 60
        url = None
        while time.monotonic() < deadline:
            if tunnel.poll() is not None:
                raise RuntimeError('Tunnel failed. See data/tunnel.log.')
            try:
                line = lines.get(timeout=1)
            except queue.Empty:
                continue
            match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if match:
                url = match.group(0)
                break
        if not url:
            raise RuntimeError('No tunnel URL within 60 seconds. See data/tunnel.log.')
        print('Tunnel URL: ' + url, flush=True)
        # Verify both public routing and that anonymous login is disabled.
        ready = False
        for _ in range(12):
            try:
                with httpx.Client(timeout=5) as client:
                    response = client.get(url + '/api/config')
                    if response.status_code == 200 and response.json().get('dev_mode') is False:
                        ready = True
                        break
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(1)
        if not ready:
            raise RuntimeError('The HTTPS tunnel is not reachable. See data/tunnel.log.')
        set_key(str(ROOT / '.env'), 'APP_URL', url)
        env['APP_URL'] = url
        # Install the menu before declaring the launch successful.
        telegram(token, 'setChatMenuButton', {'menu_button': {'type': 'web_app', 'text': 'Играть', 'web_app': {'url': url}}})
        telegram(token, 'setMyName', {'name': 'Крысиные бега'})
        bot_log = open(logdir / 'telegram-bot.log', 'a', encoding='utf-8')
        logs.append(bot_log)
        bot = subprocess.Popen([sys.executable, '-m', 'app.bot'], cwd=ROOT, env=env, stdout=bot_log, stderr=subprocess.STDOUT)
        children.append(bot)
        print(f'READY: https://t.me/{username}', flush=True)
        print('Open the bot and tap its menu button. Keep this process running. Ctrl+C stops all three services.', flush=True)
        print('Room invitations work through /start; Main Mini App configuration is optional.', flush=True)
        while True:
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError('A service stopped. Check logs in data/.')
            time.sleep(1)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        for log in logs:
            log.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Stopped.')
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
