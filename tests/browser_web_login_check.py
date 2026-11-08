"""Production-mode web guests and Telegram users share the same live room."""
from contextlib import ExitStack
import hashlib,hmac,json,os,tempfile,time
from pathlib import Path
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright,expect
from browser_check import server,ROOT,ARTIFACTS


def signed_telegram(code):
    data={'auth_date':str(int(time.time())),'user':json.dumps({'id':54321,'first_name':'Telegram Player'})}
    secret=hmac.new(b'WebAppData',b'web-browser-test-token',hashlib.sha256).digest()
    data['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(data.items())).encode(),hashlib.sha256).hexdigest()
    return dict(initData=urlencode(data),initDataUnsafe=dict(start_param=code))


def web_login(page,url,name):
    page.goto(url)
    expect(page.locator('#login')).to_be_visible()
    page.locator('#name').fill(name);page.locator('#login-form button').click()
    expect(page.locator('#game' if '?room=' in url else '#home')).to_be_visible()


def check(browser,url):
    with ExitStack() as stack:
        host_context=stack.enter_context(browser.new_context())
        tg_context=stack.enter_context(browser.new_context())
        web_context=stack.enter_context(browser.new_context(viewport=dict(width=390,height=844)))
        host,tg,web=host_context.new_page(),tg_context.new_page(),web_context.new_page()
        errors=[]
        for page in (host,tg,web):page.on('pageerror',lambda e:errors.append(str(e)))
        host.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copiedInvite=text;}}})")
        web_login(host,url,'Web Host')
        assert host.evaluate('config.dev_mode') is False
        host.locator('[data-role="host"]').click();host.locator('#pack').select_option('library-example-race');host.locator('#create').click()
        expect(host.locator('#lobby')).to_be_visible();code=host.evaluate('room.code')
        host.locator('#invite').click();host.wait_for_function('window.copiedInvite?.includes("?room=")')
        assert host.evaluate('window.copiedInvite')==url+'/?room='+code
        host.locator('#invite-telegram').click();host.wait_for_function('window.copiedInvite?.includes("https://t.me/")')
        assert host.evaluate('window.copiedInvite')=='https://t.me/test_quiz_bot?start='+code
        # A Telegram Mini App must replace an earlier browser profile in the same tab.
        web_login(tg,url,'Old Browser Profile')
        assert tg.evaluate('auth.user.id').startswith('web-')
        tg.route('https://telegram.org/js/telegram-web-app.js',lambda route:route.fulfill(status=200,body=''))
        payload=json.dumps(signed_telegram(code))
        tg.add_init_script('window.Telegram={WebApp:{...'+payload+',ready(){},expand(){},openTelegramLink(){}}}')
        tg.goto(url+'/?room='+code)
        expect(tg.locator('#lobby')).to_be_visible();assert tg.evaluate('auth.user.id')=='54321'
        web_login(web,url+'/?room='+code,'Web Player')
        expect(web.locator('#lobby')).to_be_visible();web_id=web.evaluate('auth.user.id')
        assert web_id.startswith('web-')
        host.wait_for_function('room.players.length===3')
        host.locator('#start').click();host.locator('#skip-intro').click()
        expect(web.locator('#answer-form')).to_be_visible();expect(tg.locator('#answer-form')).to_be_visible()
        answer=host.evaluate('room.question.answer')
        for page in (web,tg):page.locator('#answer-text').fill(answer);page.locator('#answer-send').click()
        expect(host.locator('[data-verdict="correct"]')).to_have_count(2)
        host.locator('[data-verdict="correct"]').first.click();host.locator('[data-verdict="correct"]').first.click()
        expect(web.locator('#solution')).to_contain_text(answer);expect(tg.locator('#solution')).to_contain_text(answer)
        # Drop tab storage, then recover the guest identity through its HTTP-only cookie.
        web.evaluate('sessionStorage.clear()');web.goto(url+'/?room='+code)
        web.wait_for_function('room?.phase==="reveal"')
        assert web.evaluate('auth.user.id')==web_id and web.evaluate('room.players.length')==3
        another=web_context.new_page();another.goto(url+'/?room='+code);another.wait_for_function('room?.phase==="reveal"')
        assert another.evaluate('auth.user.id')==web_id and another.evaluate('room.players.length')==3
        assert web.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        web.locator('#leave').click();web.locator('#web-logout').click()
        expect(web.locator('#login')).to_be_visible()
        web.reload();expect(web.locator('#login')).to_be_visible()
        assert not errors,errors
        print('Production web + Telegram: shared room, answers, grading, both invitations, cookie recovery and mobile layout passed.',flush=True)


def main():
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='web-login-check-') as tmp,ExitStack() as stack:
        folder=Path(tmp)
        env=dict(os.environ,DEV_MODE='false',BOT_TOKEN='web-browser-test-token',BOT_USERNAME='test_quiz_bot',
            DATABASE_PATH=str(folder/'game.sqlite3'),GAME_PACKS_DIR=str(folder/'games'))
        url=stack.enter_context(server('app.main:app',env,ARTIFACTS/'web-login-game.log'))
        pw=stack.enter_context(sync_playwright())
        for name in os.environ.get('WEB_LOGIN_BROWSERS','chromium,firefox,webkit').split(','):
            with getattr(pw,name).launch() as browser:check(browser,url)
            print(name+': web login passed',flush=True)


if __name__=='__main__':main()
