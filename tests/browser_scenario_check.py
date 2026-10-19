"""Adversarial UI scenarios on disposable data: delayed replies and edit conflicts."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import tempfile

from playwright.sync_api import sync_playwright, expect
from browser_check import server, login, ARTIFACTS, PASSWORD, hash_password, ROOT
from app.store import Store


def check_room(page, screen, url, database):
    login(page,url,'Audit Host')
    db=Store(database);host=page.evaluate('auth.user')
    code=db.create(host,questions=[dict(id='audio',text='Audio question',answer='Yes',value=100,seconds=3600,
                                      media=dict(kind='audio',url='/static/demo/signals.wav'))])
    db.change(code,dict(id='audit-player',name='Player'),'join')
    page.goto(url+'/?room='+code);screen.goto(url+'/display?room='+code)
    page.locator('#start').click();page.locator('#skip-intro').click()
    expect(screen.locator('#display-media-unlock')).to_be_visible()
    page.locator('#pause-game').click()
    expect(screen.locator('#display-media-unlock')).to_be_hidden()
    page.locator('#continue-game').click()
    expect(screen.locator('#display-media-unlock')).to_be_visible()
    page.locator('#close').click();page.locator('#end-round').click()
    expect(screen.locator('#display-media-unlock')).to_be_hidden()
    page.locator('#round-next').click()
    expect(screen.locator('#finished')).to_be_visible()
    expect(screen.locator('#display-media-unlock')).to_be_hidden()
    old=page.evaluate('room');old['version']+=100;old['ui_version']+=100
    pending=[]
    page.route('**/api/rooms/*/action',lambda route:pending.append(route))
    page.evaluate("() => {window.commandDone=false;command('reaction',{text:'🔥'}).then(()=>window.commandDone=true);}")
    page.locator('#leave').click()
    assert pending
    pending.pop().fulfill(status=200,content_type='application/json',body=json.dumps(old))
    page.wait_for_function('window.commandDone')
    expect(page.locator('#home')).to_be_visible();expect(page.locator('#game')).to_be_hidden()
    assert page.evaluate('room===null')
    page.unroute('**/api/rooms/*/action')


def check_pending_grade(page,url,database):
    db=Store(database);host=page.evaluate('auth.user');player=dict(id='grade-player',name='Grade Player')
    code=db.create(host,questions=[dict(id='grade',text='Grade question',answer='Yes',value=100,seconds=3600)])
    db.change(code,player,'join')
    page.goto(url+'/?room='+code);page.locator('#start').click();page.locator('#skip-intro').click()
    response=page.request.post(url+'/api/rooms/'+code+'/action',headers={'Authorization':'Bearer '+db.session(player)},data=dict(action='answer',text='Yes'))
    assert response.ok
    expect(page.locator('[data-verdict="correct"]')).to_be_visible()
    old=page.evaluate('room');old['version']+=100;old['ui_version']+=100
    pending=[];page.route('**/api/rooms/*/action',lambda route:pending.append(route))
    page.locator('[data-verdict="correct"]').click();page.locator('#leave').click()
    assert pending
    pending.pop().fulfill(status=200,content_type='application/json',body=json.dumps(old))
    page.wait_for_function('pendingGrades.size===0')
    expect(page.locator('#home')).to_be_visible();assert page.evaluate('room===null')
    page.unroute('**/api/rooms/*/action')


def check_conflict(first,second,url):
    first.goto(url)
    first.get_by_label('Пароль конструктора',exact=True).fill(PASSWORD)
    first.get_by_role('button',name='Войти в мастерскую').click()
    first.get_by_role('button',name='+ Новая игра',exact=True).click()
    first.get_by_label('Название игры',exact=True).fill('Concurrent editing')
    first.get_by_role('button',name='Создать игру →',exact=True).click()
    first.get_by_role('tab',name='Раунды',exact=True).click()
    first.locator('#add-question').click()
    first.locator('#question-text').fill('Original question');first.locator('#answer').fill('Yes')
    first.locator('#save').click();expect(first.locator('#save-status')).to_have_text('Черновик сохранён')
    game=first.evaluate('state.snapshot.id')
    second.goto(url);second.locator('[data-game="'+game+'"]').click()
    second.get_by_role('tab',name='Раунды',exact=True).click()
    second.locator('#question-text').fill('Saved in second tab');second.locator('#save').click()
    expect(second.locator('#save-status')).to_have_text('Черновик сохранён')
    first.locator('#question-text').fill('Unsaved in first tab');first.locator('#save').click()
    expect(first.locator('#notice')).to_contain_text('другом окне')
    expect(first.locator('#question-text')).to_have_value('Unsaved in first tab')
    assert first.evaluate('state.dirty')
    first.once('dialog',lambda dialog:dialog.accept())
    first.locator('[data-game="'+game+'"]').click()
    expect(first.locator('#question-text')).to_have_value('Saved in second tab')


def check_hidden_video_preview(page):
    page.locator('#material-panel > summary').click()
    page.locator('#media-type').select_option('video')
    page.locator('#media-file').set_input_files(str(ROOT/'static/demo/colors.mp4'))
    expect(page.locator('#media-file')).to_be_enabled()
    page.locator('#media-show-in-question').uncheck()
    page.locator('#preview-panel > summary').click()
    page.wait_for_function("document.querySelector('#preview-media video')?.readyState>=1")
    expect(page.locator('#preview-media video')).to_be_hidden()
    expect(page.locator('#preview-media')).not_to_contain_text('Материал не найден')
    page.locator('#preview-media button').click()
    page.wait_for_function("!document.querySelector('#preview-media video').paused")
    page.locator('#preview-media button').click()
    page.wait_for_function("document.querySelector('#preview-media video').paused")


def main():
    ARTIFACTS.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rat-scenarios-') as temporary, ExitStack() as stack:
        root=Path(temporary);database=root/'game.sqlite3'
        env=dict(os.environ,DEV_MODE='true',BOT_TOKEN='',DATABASE_PATH=str(database),
                 BUILDER_DATA_DIR=str(root/'builder'),GAME_PACKS_DIR=str(root/'games'),
                 BUILDER_PASSWORD_HASH=hash_password(PASSWORD))
        game=stack.enter_context(server('app.main:app',env,ARTIFACTS/'audit-game.log'))
        builder=stack.enter_context(server('builder.main:app',env,ARTIFACTS/'audit-builder.log'))
        pw=stack.enter_context(sync_playwright())
        for name in os.environ.get('SCENARIO_BROWSERS','chromium,firefox,webkit').split(','):
            with getattr(pw,name).launch() as browser:
                errors=[]
                with browser.new_context() as context,browser.new_context() as display_context:
                    page,screen=context.new_page(),display_context.new_page()
                    second=context.new_page()
                    for tab in (page,screen,second):tab.on('pageerror',lambda error:errors.append(str(error)))
                    try:
                        check_room(page,screen,game,database)
                        check_pending_grade(page,game,database)
                        check_conflict(page,second,builder)
                        if name!='webkit':check_hidden_video_preview(page)
                        assert not errors,errors
                        print(name+': UI scenarios complete',flush=True)
                    except Exception:
                        for index,tab in enumerate((page,screen,second)):
                            tab.screenshot(path=ARTIFACTS/('audit-'+name+'-'+str(index)+'.png'),full_page=True)
                        raise
            print(name+': delayed replies, sound prompts and edit conflicts passed',flush=True)


if __name__=='__main__':
    main()
