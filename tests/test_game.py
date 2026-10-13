import hashlib
import hmac
import json
import time
from urllib.parse import urlencode
import pytest
from app.auth import validate_telegram

def signed(token,age=0):
    d={'auth_date':str(int(time.time())-age),'user':json.dumps({'id':123,'first_name':'Тест'})}
    secret=hmac.new(b'WebAppData',token.encode(),hashlib.sha256).digest()
    d['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(d.items())).encode(),hashlib.sha256).hexdigest()
    return urlencode(d)

def test_auth():
    assert validate_telegram(signed('secret'),'secret')['id']=='123'
    for raw,token in [(signed('secret'),'wrong'),(signed('secret',90000),'secret'),('user=fake','secret')]:
        with pytest.raises(ValueError): validate_telegram(raw,token)


def test_bot_room_invitation():
    from app.bot import invitation_url
    assert invitation_url('https://example.com', '/start ABC234')=='https://example.com?room=ABC234'
    assert invitation_url('https://example.com/?mode=test', '/start abc234')=='https://example.com/?mode=test&room=ABC234'
    assert invitation_url('https://example.com', '/start')=='https://example.com'
    assert invitation_url('https://example.com', '/start https://other.example')=='https://example.com'


def test_bot_profile_rate_limit_does_not_block_startup():
    import asyncio
    from app.bot import configure_bot
    calls=[]
    async def configured(method, **payload):
        calls.append(method)
        if method=='getChatMenuButton': return {'web_app':{'url':'https://example.com/'}}
        if method=='getMyName': return {'name':'Крысиные бега'}
        raise AssertionError('Already configured profile should not be changed')
    asyncio.run(configure_bot(configured,'https://example.com'))
    assert 'setMyName' not in calls and 'setChatMenuButton' not in calls
    async def limited(method, **payload):
        if method=='getChatMenuButton': return {'web_app':{'url':'https://example.com'}}
        if method=='getMyName': return {'name':'Old name'}
        if method=='setMyName': raise RuntimeError('Too Many Requests: retry after 85061')
        raise AssertionError(method)
    # This used to abort the bot before it could start receiving messages.
    asyncio.run(configure_bot(limited,'https://example.com'))

