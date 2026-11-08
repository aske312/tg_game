"""Mobile player usability: action reachability, keyboard geometry and game states."""
from contextlib import ExitStack
from pathlib import Path
import os,tempfile
from playwright.sync_api import sync_playwright,expect
from browser_check import ROOT,ARTIFACTS,server
from app.store import Store
from app.modes import stages_from_doc


def geometry(page,selector):
    return page.locator(selector).evaluate('(e)=>({top:e.getBoundingClientRect().top,bottom:e.getBoundingClientRect().bottom,height:e.getBoundingClientRect().height,width:e.getBoundingClientRect().width,font:parseFloat(getComputedStyle(e).fontSize)})')


def fits(page,selector):
    box=geometry(page,selector)
    assert box['top']>=-1 and box['bottom']<=page.evaluate('innerHeight')+1,(selector,box)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),'Horizontal page overflow'


def check(browser,url,database,width,height,name):
    with browser.new_context(viewport=dict(width=width,height=height),has_touch=True) as context:
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(url);expect(page.locator('#login')).to_be_visible()
        assert geometry(page,'#name')['font']>=16;assert geometry(page,'#login-form button')['height']>=44
        fits(page,'#login-form button')
        page.locator('#name').fill('ИгрокОченьДлинноеИмяБезПробелов');page.locator('#name').press('Enter')
        expect(page.locator('#home')).to_be_visible()
        fits(page,'#join-submit')
        if width==320:page.screenshot(path=ARTIFACTS/('mobile-'+name+'-home.png'))
        db=Store(database);host=dict(id='mobile-host-'+os.urandom(6).hex(),name='Host');player=page.evaluate('auth.user')
        stages=stages_from_doc({'stages':[dict(id='t',type='blitz',title='Text'),dict(id='c',type='binary',title='Choices'),dict(id='g',type='grid',title='Buzzer',answer_mode='single',categories=['Topic'])]})
        long='Прочитай вопрос до конца и выбери правильный ответ. '*24
        questions=[dict(id='text',stage='t',type='question',category='Topic',text=long,answer='Да',value=100,seconds=3600),
            dict(id='choice',stage='c',type='question',category='Topic',text=long,answer='Первый вариант',choices=['Первый вариант с длинным названием','Второй вариант с длинным названием'],correct_choice=0,value=100,seconds=3600),
            dict(id='buzz',stage='g',type='question',category='Topic',text=long,answer='Да',value=100,seconds=3600)]
        code=db.create(host,questions=questions,stages=stages);token=db.session(host)
        def action(kind,**kw):
            r=page.request.post(url+'/api/rooms/'+code+'/action',headers={'Authorization':'Bearer '+token},data=dict(action=kind,**kw))
            assert r.ok,(kind,r.status,r.text())
            return r.json()
        page.goto(url+'/?room='+code);expect(page.locator('#lobby')).to_be_visible()
        action('start');action('next')
        page.wait_for_function("document.body.dataset.mobileAnswer==='text'")
        fits(page,'#answer-form');assert geometry(page,'#answer-send')['height']>=44
        assert geometry(page,'#answer-text')['font']>=16
        assert page.locator('#answer-text').get_attribute('enterkeyhint')=='send'
        if width==320:page.screenshot(path=ARTIFACTS/('mobile-'+name+'-question.png'))
        # The last lines remain reachable above the fixed answer controls.
        page.evaluate("() => {const q=document.querySelector('#question-text').getBoundingClientRect();const form=document.querySelector('#answer-form').getBoundingClientRect();scrollBy(0,q.bottom-form.top+12)}")
        assert geometry(page,'#question-text')['bottom']<=geometry(page,'#answer-form')['top']+1
        page.locator('#answer-text').fill('Черновик');action('reaction',text='🔥')
        page.wait_for_function('room.reactions?.length>0');expect(page.locator('#answer-text')).to_have_value('Черновик')
        # Desktop automation cannot open a phone OS keyboard; emulate VisualViewport occlusion.
        inset=min(280,max(120,height-260))
        page.evaluate("""inset=>{window.savedViewport=window.visualViewport;Object.defineProperty(window,'visualViewport',{configurable:true,value:{height:innerHeight-inset,offsetTop:0,scale:1}});updateMobileClient()}""",inset)
        page.wait_for_function("document.body.dataset.mobileKeyboardOpen==='true'")
        assert geometry(page,'#answer-form')['bottom']<=height-inset+1
        assert geometry(page,'#answer-form')['top']>=0
        action('pause');page.wait_for_function("document.body.dataset.mobileAnswer==='none'")
        assert page.evaluate("document.activeElement.id!=='answer-text'")
        page.evaluate("Object.defineProperty(window,'visualViewport',{configurable:true,value:window.savedViewport});updateMobileClient()")
        action('unpause');page.wait_for_function("document.body.dataset.mobileAnswer==='text'")
        expect(page.locator('#answer-text')).to_have_value('Черновик')
        page.locator('#answer-text').fill('Да');page.locator('#answer-text').press('Enter')
        page.wait_for_function("document.body.dataset.mobileAnswer==='sent'");fits(page,'#my-answer')
        action('correct',question='text',player=player['id'])
        page.wait_for_function("document.body.dataset.mobileAnswer==='none'")
        if width in (320,390,844):
            action('end_round');action('next');action('next')
            page.wait_for_function("document.body.dataset.mobileAnswer==='binary'");fits(page,'#binary-options')
            assert geometry(page,'[data-choice="0"]')['height']>=44
            page.locator('[data-choice="0"]').click();page.wait_for_function('room.phase==="reveal"')
            action('end_round');action('next');action('next');action('pick',question='buzz')
            page.wait_for_function("document.body.dataset.mobileAnswer==='buzz'");fits(page,'#buzz-answer')
            page.locator('#buzz-answer').click();page.wait_for_function("document.body.dataset.mobileAnswer==='text'")
            page.locator('#answer-text').fill('Да');page.locator('#answer-text').press('Enter')
            page.wait_for_function("document.body.dataset.mobileAnswer==='sent'")
            action('correct',question='buzz',player=player['id']);action('end_round');action('show_scores')
            expect(page.locator('#round-scores')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            action('next');page.wait_for_function('room.phase==="finished"')
            page.evaluate('ceremonyStart=Date.now()/1000+offset/1000-30;tickExperience()')
            page.locator('#another').click();expect(page.locator('#home')).to_be_visible()
            page.wait_for_function("document.body.dataset.mobileAnswer==='none'")
        if width==320:
            code=db.create(host,questions=[dict(id='timeout',type='question',category='Topic',text=long,answer='Да',value=100,seconds=1)])
            page.goto(url+'/?room='+code);expect(page.locator('#lobby')).to_be_visible()
            action('start');action('next')
            page.wait_for_function("document.body.dataset.mobileAnswer==='expired'")
            fits(page,'#timeout-hint');expect(page.locator('#timeout-hint')).to_contain_text('Время вышло')
        assert not errors,errors
        print(f'{name} {width}x{height}: entry, reachable controls, draft, simulated keyboard and game states passed',flush=True)


def main():
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mobile-client-') as temp,ExitStack() as stack:
        database=Path(temp)/'game.sqlite3'
        env=dict(os.environ,DEV_MODE='false',BOT_USERNAME='test_bot',DATABASE_PATH=str(database))
        url=stack.enter_context(server('app.main:app',env,ARTIFACTS/'mobile-client.log'))
        pw=stack.enter_context(sync_playwright())
        for name in os.environ.get('MOBILE_BROWSERS','chromium,firefox,webkit').split(','):
            with getattr(pw,name).launch() as browser:
                for width,height in [(320,568),(360,740),(390,844),(430,932),(844,390)]:check(browser,url,database,width,height,name)


if __name__=='__main__':main()
