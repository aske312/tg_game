"""Optional Telegram launcher bot: python -m app.bot."""
import asyncio
import logging
import os
import re
from urllib.parse import urlparse, urlsplit, urlunsplit, parse_qsl, urlencode

import httpx
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)


def invitation_url(base, text):
    parts = text.split(maxsplit=1)
    code = parts[1].strip().upper() if len(parts) > 1 else ''
    if not re.fullmatch(r'[A-Z2-9]{6}', code):
        return base
    url = urlsplit(base)
    query = dict(parse_qsl(url.query))
    query['room'] = code
    return urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), url.fragment))


async def main():
    token = os.getenv('BOT_TOKEN', '')
    url = os.getenv('APP_URL', '')
    if not token or urlparse(url).scheme != 'https':
        raise SystemExit('Заполните BOT_TOKEN и APP_URL (HTTPS) в .env')
    async with httpx.AsyncClient(timeout=40) as client:
        async def call(method, **payload):
            # Do not log request URLs: the bot token is part of the URL.
            try:
                response = await client.post(f'https://api.telegram.org/bot{token}/{method}', json=payload)
                data = response.json()
            except (httpx.HTTPError, ValueError):
                raise RuntimeError('Не удалось связаться с Telegram') from None
            if not data.get('ok'):
                raise RuntimeError(data.get('description', 'Ошибка Telegram'))
            return data['result']

        logging.getLogger('httpx').setLevel(logging.WARNING)
        await call('setChatMenuButton', menu_button={'type': 'web_app', 'text': 'Играть', 'web_app': {'url': url}})
        await call('setMyName', name='Крысиные бега')
        offset = 0
        print('Бот запущен. Ожидаю /start в личном чате.')
        while True:
            try:
                updates = await call('getUpdates', offset=offset, timeout=25, allowed_updates=['message'])
                for update in updates:
                    offset = update['update_id'] + 1
                    msg = update.get('message', {})
                    if msg.get('chat', {}).get('type') == 'private' and msg.get('text', '').split(' ')[0] in ('/start', '/play'):
                        launch = invitation_url(url, msg.get('text', ''))
                        await call('sendMessage', chat_id=msg['chat']['id'],
                                   text='Крысиные бега 🐀\nСоздайте комнату или попробуйте тренировку с искусственными игроками. Ответы пишите в чат комнаты.',
                                   reply_markup={'inline_keyboard': [[{'text': 'Открыть игру', 'web_app': {'url': launch}}]]})
            except RuntimeError as e:
                print(str(e))
                await asyncio.sleep(3)


if __name__ == '__main__':
    asyncio.run(main())
