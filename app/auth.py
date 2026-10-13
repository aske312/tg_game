import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def validate_telegram(raw: str, token: str) -> dict:
    pairs = parse_qsl(raw, keep_blank_values=True)
    data = dict(pairs)
    if len(pairs) != len(data):
        raise ValueError('Некорректные данные Telegram')
    received = data.pop('hash', '')
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    check = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not token or not hmac.compare_digest(expected, received):
        raise ValueError('Не удалось проверить вход через Telegram')
    age = time.time() - int(data.get('auth_date', '0'))
    if age < -30 or age > 86400:
        raise ValueError('Вход устарел. Откройте приложение заново')
    user = json.loads(data.get('user', '{}'))
    if not isinstance(user.get('id'), int) or not user.get('first_name'):
        raise ValueError('Нет данных пользователя Telegram')
    return {'id': str(user['id']), 'name': str(user['first_name'])[:64]}
