// Run with: node --test tests/ui_game.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'..');

test('single answer shows the buzzer then input only for its winner',()=>{
  const h=harness();
  const stage={id:'g',type:'grid',title:'Grid',answer_mode:'single'};
  h.apply({stage,can_buzz:true,can_answer:false,display_scene:'question'});
  assert(!h.node('buzz-answer').hidden);assert(h.node('answer-form').hidden);
  h.apply({stage,can_buzz:false,can_answer:true,responder:'p',display_scene:'question'});
  assert(h.node('buzz-answer').hidden);assert(!h.node('answer-form').hidden);
  h.apply({stage,can_buzz:false,can_answer:false,responder:'other',display_scene:'question'});
  assert(h.node('buzz-answer').hidden);assert(h.node('answer-form').hidden);
});

test('host can grade an oral buzzer answer before any text is submitted',()=>{
  const h=harness();h.run("auth.user.id='h'");
  const stage={id:'g',type:'grid',title:'Grid',answer_mode:'single'};
  const state={stage,phase:'question',responder:'p',deadline:null,buzz_remaining:38,single_closed:false,answers:{}};
  h.apply(state);
  assert.equal(h.node('phase').textContent,'Игрок отвечает');
  assert.match(h.node('review-list').innerHTML,/Player.*голосом.*data-player="p".*Верно.*Неверно/s);
  assert(h.node('host-answers').hidden);assert.match(h.node('timer').textContent,/38 сек/);
  h.advance(120000);assert.match(h.node('timer').textContent,/38 сек/);
  h.run("auth.user.id='p'");
  h.apply({...state,responder:null,buzz_remaining:null,deadline:1160,can_buzz:false,can_answer:false,
    answers:{p:{text:'',oral:true,verdict:'wrong',points:-100}},answered_ids:['p']});
  assert(h.node('buzz-answer').hidden);assert(h.node('answer-form').hidden);
  assert.match(h.node('my-answer').textContent,/-100.*продолжается/s);
  h.run("auth.user.id='other'");
  h.apply({...state,responder:null,buzz_remaining:null,deadline:1160,can_buzz:true,can_answer:false,answers:{},answered_ids:['p']});
  assert(!h.node('buzz-answer').hidden);
});

test('video can play as audio for the question and reveal the full video after grading',()=>{
  const h=harness();
  const question={id:'q1',text:'Song?',answer:'Yes',media:{kind:'video',url:'/clip.webm',start:20,end:30,audio_only:true}};
  h.apply({display:true,question,media_playback:{question:'q1',mode:'excerpt',playing:true,position:0,updated_at:1000,revision:0}});
  const audio=h.node('media-content').children[0].children[0];
  assert.equal(audio.tagName,'VIDEO');assert(audio.hidden);
  audio.emit('loadedmetadata');assert(h.run('activeClip.ready'));
  h.apply({display:true,phase:'reveal',question,display_scene:'answer',media_playback:{question:'q1',mode:'full',playing:true,position:0,updated_at:1000,revision:1}});
  const video=h.node('media-content').children[0].children[0];
  assert.equal(video.tagName,'VIDEO');assert(!video.hidden);
  video.emit('loadedmetadata');assert(h.run('activeClip.ready'));
});

test('score pause shows completed round points and live points for the current round',()=>{
  const h=harness();h.apply({display:true,paused:true,pause_view:'scores',stage_number:2,score_stage:'b',stage_start_scores:{p:100},
    stages:[{id:'g',title:'First'},{id:'b',title:'Second'}],stage:{id:'b',type:'blitz',title:'Second'},
    players:[{id:'h',name:'Host',score:0},{id:'p',name:'Player',score:125}],
    round_results:[{stage_id:'g',players:[{id:'p',name:'Player',round_points:100,score:100}]}]});
  assert.match(h.node('presentation-results').innerHTML,/First.*Second.*\+100.*\+25.*125 очков/s);
});

test('host scenes preserve answers and full media uses the whole file timeline',()=>{
  const h=harness();
  const question={id:'q1',text:'Song?',category:'Music',value:100,answer:'Artist',media:{kind:'audio',url:'/song.wav',start:20,end:30}};
  h.apply({display:true,phase:'reveal',question,display_scene:'answer',media_playback:{question:'q1',mode:'full',playing:true,position:0,updated_at:1000,revision:1}});
  const clip=h.node('media-content').children[0];clip.children[0].emit('loadedmetadata');
  assert.equal(clip.children.length,1);assert.equal(clip.children[0].currentTime,0);
  assert(!h.node('solution').hidden);assert(!h.node('question').hidden);assert(h.node('question-board').hidden);
  h.apply({display:true,phase:'reveal',question,display_scene:'board'});
  assert(h.node('question').hidden);assert(!h.node('question-board').hidden);
  h.apply({display:true,phase:'reveal',question,display_scene:'answer',paused:true,paused_at:1000,pause_view:'scores'});
  assert(h.node('question').hidden);assert(h.node('question-board').hidden);assert(!h.node('presentation-scores').hidden);
  assert(h.node('pause-panel').hidden);assert(h.node('round-scores').hidden);
  assert.match(h.node('presentation-results').innerHTML,/Player/);
  h.apply({display:true,phase:'reveal',question,display_scene:'question'});
  assert(!h.node('question').hidden);assert(h.node('solution').hidden);
});

test('score pause replaces the whole scene with scores, players keep the pause notice',()=>{
  const h=harness();
  for(const phase of ['question','review','reveal','board','intro']){
    h.apply({display:true,phase,paused:true,paused_at:1000,pause_view:'scores',display_scene:phase==='board'?'board':'question'});
    assert(!h.node('presentation-scores').hidden,phase);
    for(const id of ['question','question-board','event','grid-intro','pause-panel','round-scores'])assert(h.node(id).hidden,id);
    assert.match(h.node('presentation-results').innerHTML,/Player/);
    assert.doesNotMatch(h.node('presentation-results').innerHTML,/data-verdict|Верно|Неверно/);
  }
  h.apply({display:true,paused:false,display_scene:'question'});
  assert(h.node('presentation-scores').hidden);assert(!h.node('question').hidden);
  h.apply({display:false,paused:true,paused_at:1000});
  assert(h.node('presentation-scores').hidden);assert(!h.node('pause-panel').hidden);
  assert(h.node('question').hidden);
});

test('game pause shows a break and can switch to scores without resuming',()=>{
  const h=harness();
  h.apply({display:true,paused:true,paused_at:1000,pause_view:'break',scores_visible:true});
  assert(!h.node('pause-panel').hidden);assert(h.node('round-scores').hidden);assert(h.node('presentation-scores').hidden);assert(h.node('question').hidden);
  h.apply({display:true,paused:true,paused_at:1000,pause_view:'scores'});
  assert(h.node('pause-panel').hidden);assert(!h.node('presentation-scores').hidden);
  h.run("auth.user.id='h'");
  h.apply({paused:true,paused_at:1000,pause_view:'break'});
  assert(h.node('pause-game').hidden);assert(!h.node('display-game-scores').hidden);assert(!h.node('continue-game').hidden);
  h.apply({paused:true,paused_at:1000,pause_view:'scores'});
  assert(!h.node('pause-game').hidden);assert(h.node('display-game-scores').hidden);assert(!h.node('continue-game').hidden);
});

function harness(options={}) {
  let clock=1000000;
  class Clock extends Date {static now(){return clock;}}
  function element(){
    let html='';
    const listeners={};
    return {hidden:false,dataset:{},style:{setProperty(){}},value:'',options:[],children:[],writes:0,textContent:'',previousElementSibling:{},
      paused:true,currentTime:0,duration:200,attributes:{},
      playCalls:0,pause(){this.paused=true;this.emit('pause');},async play(){this.playCalls++;this.paused=false;this.emit('play');},
      emit(event){for(const fn of listeners[event]||[])fn();},
      get innerHTML(){return html;},set innerHTML(value){html=value;this.writes++;},
      querySelectorAll(){return [];},querySelector(){return null;},setAttribute(key,value){this.attributes[key]=value;},addEventListener(event,fn){(listeners[event]??=[]).push(fn);},
      replaceChildren(){this.children=[];},append(node){this.children.push(node);},remove(){},
    };
  }
  const nodes=new Map([...fs.readFileSync(path.join(root,'static/index.html'),'utf8').matchAll(/id="([^"]+)"/g)].map(m=>[m[1],element()]));
  const storage=new Map(Object.entries(options.storage||{}));
  const ctx={document:{getElementById(id){assert(nodes.has(id),'Missing DOM ID: '+id);return nodes.get(id);},querySelectorAll(){return [];},createElement(name){return {...element(),tagName:name.toUpperCase()};},addEventListener(){},body:{dataset:{}}},
    window:{addEventListener(){},matchMedia(){return {matches:false};}},sessionStorage:{getItem(key){return storage.get(key)??null;},setItem(key,value){storage.set(key,value);},removeItem(key){storage.delete(key);}},location:{search:'',pathname:options.pathname||'/',origin:'http://localhost'},history:{replaceState(){}},URLSearchParams,
    fetch:()=>new Promise(()=>{}),setInterval(){},setTimeout(){},clearTimeout(){},Date:Clock,console};
  vm.createContext(ctx);
  for(const file of ['experience.js','playback.js','app.js'])vm.runInContext(fs.readFileSync(path.join(root,'static',file),'utf8'),ctx);
  vm.runInContext("auth={user:{id:'p',name:'Player'}}",ctx);
  let version=0;
  const base={code:'ABC234',host:'h',players:[{id:'h',name:'Host',score:0},{id:'p',name:'Player',score:0}],phase:'question',stage:{id:'g',title:'Grid',type:'grid',categories:['Space']},stages:[{id:'g',type:'grid'}],stage_count:1,stage_number:1,question_count:2,question_number:1,round_count:2,used:[],answered_ids:[],answers:{},question:{id:'q1',category:'Space',text:'Question',value:100,seconds:45},active:'q1',deadline:1045,chooser:'h',board:[{id:'q2',category:'Space',value:200,used:false}],can_pick:false};
  const apply=patch=>{ctx.snapshot={...base,version:++version,ui_version:version,server_time:clock/1000,...patch};vm.runInContext('apply(snapshot)',ctx);return ctx.snapshot;};
  const node=id=>nodes.get(id);
  return {ctx,apply,node,storage,run:code=>vm.runInContext(code,ctx),advance:ms=>{clock+=ms;vm.runInContext('tick()',ctx);}};
}

test('reaction snapshots preserve answer input and binary/board DOM',()=>{
  const h=harness(),state=h.apply({});
  h.node('answer-text').value='My draft';
  const boardWrites=h.node('board-cells').writes,binaryWrites=h.node('binary-options').writes;
  h.apply({...state,version:state.version+1,reactions:[{id:1,time:1000,emoji:'🔥'}]});
  assert.equal(h.node('answer-text').value,'My draft');
  assert.equal(h.node('board-cells').writes,boardWrites);
  assert.equal(h.node('binary-options').writes,binaryWrites);
  assert.equal(h.node('reaction-stream').children.length,1);
  h.apply({...state,version:state.version+1,reactions:[{id:1,time:1000,emoji:'🔥'}]});
  assert.equal(h.node('reaction-stream').children.length,1);
});

test('player sees exactly one of grid selection, waiting and question',()=>{
  const h=harness();
  h.apply({phase:'reveal',can_pick:true,chooser:'p'});
  assert(!h.node('question-board').hidden);assert(h.node('question').hidden);assert(h.node('board-waiting').hidden);
  h.apply({phase:'board',question:null,active:null});
  assert(h.node('question-board').hidden);assert(h.node('question').hidden);assert(!h.node('board-waiting').hidden);
  h.apply({});
  assert(!h.node('question').hidden);assert(h.node('question-board').hidden);assert(h.node('board-waiting').hidden);
});

test('pause keeps countdown frozen and round scores replace the question',()=>{
  const h=harness();h.apply({paused:true,paused_at:1010});
  const timer=h.node('timer').textContent;
  h.advance(90000);
  assert.equal(h.node('timer').textContent,timer);
  assert(h.node('question').hidden);assert(!h.node('pause-panel').hidden);
  h.apply({phase:'reveal',stage_complete:true,scores_visible:true});
  assert(!h.node('round-scores').hidden);assert(h.node('question').hidden);assert(h.node('pause-panel').hidden);
  assert.match(h.node('round-results').innerHTML,/Player/);
});

test('expired questions keep waiting for host and show skipped-answer penalties privately',()=>{
  const host=harness();host.run("auth.user.id='h'");
  host.apply({deadline:999,can_answer:false,time_expired:true});
  assert(!host.node('question').hidden);assert(!host.node('timeout-hint').hidden);
  assert.match(host.node('close').textContent,/Завершить вопрос.*1/);
  assert(!host.node('close-hint').hidden);assert(host.node('review-list').innerHTML==='');
  const screen=harness();screen.apply({display:true,deadline:999,time_expired:true});
  assert(!screen.node('question').hidden);assert(screen.node('solution').hidden);assert(!screen.node('timeout-hint').hidden);
  const player=harness();player.apply({deadline:999,can_answer:false,time_expired:true});
  assert(player.node('answer-form').hidden);assert(player.node('answer-send').disabled);
  player.apply({phase:'review',omission_penalties:{p:-100}});
  assert(!player.node('my-answer').hidden);assert.match(player.node('my-answer').textContent,/-100/);
  player.apply({phase:'review',omission_penalties:{p:0}});
  assert(!player.node('my-answer').hidden);assert.match(player.node('my-answer').textContent,/0 очков/);
});

test('round scores offer only the host a next-round action',()=>{
  for(const role of ['host','player','display']){
    const h=harness();if(role==='host')h.run("auth.user.id='h'");
    h.apply({display:role==='display',phase:'reveal',stage_complete:true,scores_visible:true,stage_count:2});
    assert(!h.node('round-scores').hidden);assert(h.node('question').hidden);assert(h.node('question-board').hidden);
    assert.equal(h.node('scores-next').hidden,role!=='host');
    assert.equal(h.node('scores-waiting').hidden,role==='host');
    assert.equal(h.node('scores-next').textContent,'Следующий раунд →');
    h.apply({display:role==='display',phase:'reveal',stage_complete:true,scores_visible:true,stage_count:1});
    assert.equal(h.node('scores-next').textContent,'К награждению →');
  }
});

test('round end waits for the host and historical results show round points and totals',async()=>{
  const results=[{stage_id:'g',stage_index:0,title:'First',players:[{id:'p',name:'Player',score:100,round_points:100}]},
    {stage_id:'b',stage_index:1,title:'Second',players:[{id:'p',name:'Player',score:50,round_points:-50}]}];
  for(const role of ['host','player','display']){
    const h=harness();if(role==='host')h.run("auth.user.id='h'");
    h.apply({display:role==='display',phase:'reveal',display_scene:'round_end',stage_complete:true,round_results:results});
    assert(!h.node('round-end').hidden);assert(h.node('question').hidden);assert(h.node('round-scores').hidden);
    assert.equal(h.node('round-next').hidden,role!=='host');assert.equal(h.node('round-results-button').hidden,role!=='host');
    const scores={display:role==='display',phase:'reveal',display_scene:'round_end',stage_complete:true,scores_visible:true,round_results:results,scores_round:'g',
      stage:{id:'b',type:'blitz',title:'Second'},stages:[{id:'g',title:'First'},{id:'b',title:'Second'}],stage_number:2,
      players:[{id:'h',name:'Host',score:0},{id:'p',name:'Player',score:50}]};
    h.apply(scores);
    assert(h.node('round-end').hidden);assert(!h.node('round-scores').hidden);
    assert.match(h.node('round-results').innerHTML,/Раунд 1.*First.*Раунд 2.*Second.*Всего.*\+100.*-50.*50 очков/s);
    assert.equal(h.node('scores-title').textContent,'Счёт по раундам');
    assert.equal(h.node('results-round'),undefined);
    h.apply({...scores,scores_round:'b'});
    assert.match(h.node('round-results').innerHTML,/\+100.*-50.*50 очков/s);
    h.apply({...scores,paused:true,pause_view:'scores'});
    if(role==='display')assert.match(h.node('presentation-results').innerHTML,/\+100.*-50.*50 очков/s);
    if(role==='host'){
      h.ctx.calls=[];h.run('command=async action=>calls.push(action)');
      await h.node('round-next').onclick();await h.node('round-results-button').onclick();
      assert.deepEqual(Array.from(h.ctx.calls),['next','show_scores']);
    }
  }
});

test('round preview survives reaction updates and waits for the host',()=>{
  const h=harness(),state=h.apply({phase:'intro',question:null,active:null,intro_started_at:1000,intro_until:null});
  assert(!h.node('grid-intro').hidden);assert(h.node('question-board').hidden);assert(h.node('question').hidden);
  const writes=h.node('round-preview-content').writes;
  h.apply({...state,version:state.version+1,reactions:[{id:1,time:1000,emoji:'👏'}]});
  assert.equal(h.node('round-preview-content').writes,writes);
  h.advance(60000);
  assert.match(h.node('intro-countdown').textContent,/по команде ведущего/);
});

test('all presentation previews explain the mode, answer controls and configured grid rules',async()=>{
  for(const [type,settings,expected] of [
    ['blitz',{order:'random'},/Блиц.*случайном порядке.*Отправить ответ/s],
    ['binary',{},/Выбор из двух.*один из двух вариантов.*сразу/s],
    ['grid',{answer_mode:'all',chooser:'host'},/Отвечают все.*выбирает ведущий.*отвечают все игроки/s],
    ['grid',{answer_mode:'single',chooser:'winner'},/Отвечает один.*первый верно ответивший.*быстрее остальных.*голосом.*Ошибка.*до первого верного/s],
  ]){
    const h=harness();
    const preview={phase:'intro',question:null,active:null,deadline:null,intro_until:null,display:true,
      stage:{id:type,type,title:'Round title <script>',categories:['Music <theme>'],...settings}};
    h.apply(preview);
    const html=h.node('round-preview-content').innerHTML;
    assert.match(html,expected);assert.match(html,/Round title &lt;script&gt;/);
    if(type==='grid')assert.match(html,/Темы раунда.*Music &lt;theme&gt;/s);
    else assert.doesNotMatch(html,/Темы раунда/);
    assert(!h.node('grid-intro').hidden);assert(h.node('skip-intro').hidden);
    for(const id of ['question','question-board','buzz-answer','binary-options','presentation-controls'])assert(h.node(id).hidden,id);
    h.run("auth.user.id='h'");h.apply({...preview,display:false});
    assert(!h.node('skip-intro').hidden);assert(h.node('presentation-controls').hidden);
    h.ctx.calls=[];h.run('command=async action=>calls.push(action)');
    await h.node('skip-intro').onclick();assert.deepEqual(Array.from(h.ctx.calls),['next']);
  }
});

test('ceremony reveals lower places then third, second and first on all player screens',()=>{
  const h=harness();
  const players=[{id:'h',name:'Host',score:0},...['First','Second','Third','Fourth','Last'].map((name,i)=>({id:'p'+i,name,score:500-i*100}))];
  h.apply({phase:'finished',question:null,active:null,finished_at:1000,players});
  assert.match(h.node('final-results').innerHTML,/Last.*Fourth/s);
  assert.doesNotMatch(h.node('final-results').innerHTML,/First|Second|Third/);
  assert.equal(h.node('scoreboard'),undefined);assert(h.node('another').hidden);
  h.advance(3200);assert.match(h.node('award-spotlight').innerHTML,/Third/);assert.doesNotMatch(h.node('final-results').innerHTML,/First|Second/);
  h.advance(4000);assert.match(h.node('award-spotlight').innerHTML,/Second/);assert.doesNotMatch(h.node('final-results').innerHTML,/First/);
  h.advance(4000);assert.match(h.node('award-spotlight').innerHTML,/First/);assert(h.node('confetti-layer').children.length>0);
  h.advance(4000);assert(!h.node('another').hidden);assert.match(h.node('final-results').innerHTML,/First.*Second.*Third.*Fourth.*Last/s);
});

test('equal scores share places in the ceremony',()=>{
  const h=harness();
  h.ctx.players=[{id:'h',name:'Host',score:0},{id:'a',name:'A',score:10},{id:'b',name:'B',score:10},{id:'c',name:'C',score:0}];
  const plan=h.run("ceremonyPlan(players,'h')");
  assert.deepEqual(Array.from(plan.ranked,p=>p.rank),[1,1,3]);
  assert.deepEqual(Array.from(plan.podium),[3,1]);
});

test('player sees trap description, remaining questions and future effects',()=>{
  const h=harness();
  const trap={kind:'half_reward',remaining:2,title:'Половина награды'};
  h.apply({round_modifiers:{p:trap},modifiers:{p:trap}});
  assert(!h.node('my-effects').hidden);
  assert.match(h.node('my-effect-list').innerHTML,/effects\.svg#half.*Половина награды.*2 вопроса.*включая текущий/s);
  assert(h.node('host-management').hidden);assert(h.node('skip-stage').hidden);
  h.apply({phase:'review',round_modifiers:{p:trap},modifiers:{p:{kind:'shield',remaining:1}}});
  assert.match(h.node('my-effect-list').innerHTML,/В этом вопросе.*Защита от штрафа.*Далее/s);
  h.apply({phase:'board',question:null,round_modifiers:{p:trap},modifiers:{}});
  assert(h.node('my-effects').hidden);
});

test('host can manage players on pause and skip to final results',()=>{
  const h=harness();h.run("auth.user.id='h'");
  h.node('manage-player').value='p';
  h.apply({paused:true,paused_at:1000,modifiers:{p:{kind:'double_penalty',remaining:3}}});
  assert(!h.node('host-management').hidden);assert(!h.node('skip-stage').hidden);
  assert.equal(h.node('adjust-score').disabled,false);
  assert.equal(h.node('managed-score').textContent,'Счёт: 0');
  assert.match(h.node('managed-effect').innerHTML,/Двойной штраф/);
  h.apply({phase:'finished',question:null,active:null,finished_at:1000});
  assert(h.node('host-management').hidden);assert(h.node('skip-stage').hidden);
});

test('host focuses on the question or grid and keeps only pending answers in review',async()=>{
  const h=harness();h.run("auth.user.id='h'");
  h.apply({phase:'lobby',question:null});
  assert.equal(h.node('host-player-count').textContent,'Игроков: 1 / 8');
  assert(h.node('host-console').hidden);assert(!h.node('host-options').hidden);
  assert.equal(h.node('scoreboard'),undefined);
  h.apply({phase:'reveal',display_scene:'answer',can_pick:true});
  assert(!h.node('question').hidden);assert(h.node('question-board').hidden);
  h.apply({phase:'reveal',display_scene:'board',can_pick:true});
  assert(h.node('question').hidden);assert(!h.node('question-board').hidden);
  const players=[{id:'h',name:'Host'},{id:'p',name:'Pending'},{id:'g',name:'Graded'},{id:'n',name:'Absent'}];
  const answers={p:{text:'Draft',verdict:null},g:{text:'Done',verdict:'correct',points:100}};
  h.apply({phase:'review',players,answers});
  assert.match(h.node('review-list').innerHTML,/Pending.*Draft/s);
  assert.doesNotMatch(h.node('review-list').innerHTML,/Graded|Absent/);
  assert.equal(h.node('host-review-status').textContent,'Проверено 1 из 2 ответов');
  h.apply({phase:'reveal',players,answers:{...answers,p:{...answers.p,verdict:'wrong'}}});
  assert.equal(h.node('review-list').innerHTML,'');
  h.ctx.calls=[];h.run('command=async(action)=>calls.push(action)');
  await h.node('next').onclick();assert.equal(h.ctx.calls[0],'display_board');
  h.apply({phase:'reveal',stage_complete:true});
  await h.node('next').onclick();assert.equal(h.ctx.calls[1],'show_scores');
  await h.node('scores-next').onclick();assert.equal(h.ctx.calls[2],'next');
});

test('display has no media controls and follows remote seeking inside the clip',async()=>{
  const h=harness({pathname:'/display'});
  h.run("sendMediaAction=async(action,position,duration)=>{room.media_playback={question:room.question.id,playing:action==='media_play',position,duration,updated_at:0,revision:1};}");
  h.apply({display:true,question:{id:'music',text:'?',media:{kind:'audio',url:'/song.mp3',start:60,end:90}}});
  const wrapper=h.node('media-content').children[0];
  const [audio]=wrapper.children;
  audio.emit('loadedmetadata');
  assert.equal(audio.controls,false);assert.equal(audio.hidden,true);
  assert.equal(audio.currentTime,60);assert.equal(wrapper.children.length,1);
  assert.equal(audio.paused,true);
  h.run("room.media_playback={question:'music',playing:true,position:0,updated_at:0,revision:1};syncMediaPlayback()");
  assert.equal(audio.paused,false);
  h.run("room.media_playback={question:'music',playing:false,position:12,updated_at:0,revision:2};syncMediaPlayback()");
  assert.equal(audio.currentTime,72);assert.equal(audio.paused,true);
  audio.currentTime=90;
  h.run("room.media_playback={question:'music',playing:true,position:0,updated_at:0,revision:3};syncMediaPlayback()");assert.equal(audio.currentTime,60);assert.equal(audio.paused,false);
  audio.currentTime=91;audio.emit('timeupdate');assert.equal(audio.currentTime,90);assert.equal(audio.paused,true);
  audio.currentTime=50;audio.emit('seeking');assert.equal(audio.currentTime,60);
});

test('audio clips clamp to actual file length and reject missing intervals',()=>{
  const h=harness({pathname:'/display'});
  h.apply({display:true,question:{id:'music',media:{kind:'audio',url:'/song.mp3',start:150,end:300}}});
  let [audio]=h.node('media-content').children[0].children;
  audio.emit('loadedmetadata');assert(h.run('activeClip.ready'));
  h.run("room.media_playback={question:'music',playing:false,position:100,updated_at:0};syncMediaPlayback()");
  assert.equal(audio.currentTime,200);
  h.apply({display:true,question:{id:'bad',media:{kind:'audio',url:'/song.mp3',start:250}}});
  [audio]=h.node('media-content').children[0].children;
  audio.emit('loadedmetadata');assert(!h.run('activeClip.ready'));
  assert.match(h.node('notice').textContent,/за пределами/);
});

test('web display enters without login and keeps host login and room storage separate',()=>{
  const h=harness({pathname:'/display',storage:{auth:'host-login',room:'HOST12'}});
  assert(!h.node('display-entry').hidden);
  assert.equal(h.node('identity').textContent,'Общий экран');
  h.apply({display:true});
  assert(h.node('display-entry').hidden);assert(!h.node('display-fullscreen').hidden);
  for(const id of ['host-management','display-invite','host-toolbar','answer-form','reactions'])assert(h.node(id).hidden,id);
  assert.equal(h.storage.get('auth'),'host-login');assert.equal(h.storage.get('room'),'HOST12');
  assert.equal(h.storage.get('displayRoom'),'ABC234');
  h.node('leave').onclick();
  assert(!h.node('display-entry').hidden);assert(h.node('home').hidden);
  assert.equal(h.storage.has('displayRoom'),false);assert.equal(h.storage.get('auth'),'host-login');
});

test('Telegram role selection only offers player and host; host has a web screen link',()=>{
  const h=harness();h.run("setRole('display')");
  assert.equal(h.run('entryRole'),'player');
  assert.equal(h.node('join-submit').textContent,'Присоединиться →');
  h.run("auth.user.id='h'");h.apply({});
  assert(!h.node('display-invite').hidden);
  assert.equal(h.node('display-url').href,'http://localhost/display?room=ABC234');
  assert(h.node('display-fullscreen').hidden);
  assert(!fs.readFileSync(path.join(root,'static/index.html'),'utf8').includes('data-role="display"'));
});

test('display lobby previews the game and grid without participants or question text',()=>{
  const h=harness({pathname:'/display'});
  h.apply({display:true,phase:'lobby',question:null,active:null,pack_title:'Космос и музыка'});
  assert(!h.node('display-preview').hidden);assert(h.node('lobby').hidden);
  assert.equal(h.node('scoreboard'),undefined);assert.equal(h.node('players'),undefined);
  assert.equal(h.node('display-preview-title').textContent,'Космос и музыка');
  assert.equal(h.node('display-preview-code').textContent,'ABC234');
  assert.equal(h.node('display-preview-rounds').textContent,'1 раунд');
  assert(!h.node('display-preview-grid').hidden);
  assert.match(h.node('display-preview-cells').innerHTML,/Space.*200/s);
  assert.doesNotMatch(h.node('display-preview-cells').innerHTML,/Question|Player|Host/);
  h.apply({display:true,phase:'lobby',stage:{id:'b',type:'blitz'},board:[],question:null});
  assert(h.node('display-preview-grid').hidden);
});

test('display shows the grid or the question as a single scene with no roster',()=>{
  const h=harness({pathname:'/display'});
  h.apply({display:true,phase:'board',question:null,active:null});
  assert(!h.node('question-board').hidden);assert(h.node('question').hidden);
  for(const phase of ['question','review','reveal']){
    h.apply({display:true,phase});
    assert(!h.node('question').hidden,phase);assert(h.node('question-board').hidden,phase);
    assert.equal(h.node('scoreboard'),undefined,phase);assert(h.node('display-preview').hidden,phase);
  }
  h.apply({display:true,phase:'board',question:null,active:null});
  assert(!h.node('question-board').hidden);assert.equal(h.node('scoreboard'),undefined);
});

test('display retains dedicated round scores and awards; host has no roster',()=>{
  const h=harness({pathname:'/display'});
  h.apply({display:true,phase:'reveal',stage_complete:true,scores_visible:true});
  assert(!h.node('round-scores').hidden);assert(h.node('question').hidden);assert.equal(h.node('scoreboard'),undefined);
  assert.match(h.node('round-results').innerHTML,/Player/);
  h.apply({display:true,phase:'finished',question:null,finished_at:1000});
  assert(!h.node('finished').hidden);assert(h.node('display-preview').hidden);assert.equal(h.node('scoreboard'),undefined);
  const host=harness();host.run("auth.user.id='h'");host.apply({phase:'lobby',question:null});
  assert.equal(host.node('scoreboard'),undefined);assert(!host.node('lobby').hidden);assert(host.node('display-preview').hidden);
});

test('player never loads audio or video; host gets remote controls and images remain visible',async()=>{
  for(const kind of ['audio','video']){
    const player=harness();player.apply({question:{id:'m',media:{kind,url:'/private-media'}}});
    assert(player.node('media-content').hidden);assert.equal(player.node('media-content').children.length,0);
    assert(player.node('host-media-controls').hidden);
    const host=harness();host.run("auth.user.id='h'");host.ctx.calls=[];
    host.run("sendMediaAction=async action=>{calls.push(action);room.media_playback={...mediaTransport(),playing:action==='media_play'};}");
    host.apply({question:{id:'m',media:{kind,url:'/private-media'}}});
    assert(!host.node('host-media-controls').hidden);assert.equal(host.node('media-content').children.length,0);
    assert.equal(host.node('display-media-toggle').textContent,'▶ Воспроизвести');
    await host.node('display-media-toggle').onclick();
    assert.equal(host.node('display-media-toggle').textContent,'Ⅱ Пауза');
    await host.node('display-media-toggle').onclick();
    assert.equal(host.node('display-media-toggle').textContent,'▶ Воспроизвести');
    assert.deepEqual(Array.from(host.ctx.calls),['media_play','media_pause']);
  }
  const image=harness();image.apply({question:{id:'image',media:{kind:'image',url:'/picture.png'}}});
  assert.equal(image.node('media-content').children[0].src,'/picture.png');assert(!image.node('media-content').hidden);
});

test('display media follows host pause/resume once and reaction updates do not restart it',()=>{
  const h=harness({pathname:'/display'}),q={id:'m',media:{kind:'video',url:'/video.mp4',start:20,end:50}};
  const playing={question:'m',playing:true,position:2,updated_at:1000,revision:0};
  const state=h.apply({display:true,question:q,media_playback:playing});
  const [video,controls]=h.node('media-content').children[0].children;video.emit('loadedmetadata');
  assert.equal(video.hidden,false);assert.equal(video.controls,false);assert.equal(video.currentTime,22);assert.equal(video.paused,false);

  const plays=video.playCalls;
  h.apply({...state,version:state.version+1,reactions:[]});assert.equal(video.playCalls,plays);
  h.apply({display:true,question:q,media_playback:{...playing,playing:false,position:7,revision:1}});
  assert.equal(video.currentTime,27);assert.equal(video.paused,true)
  h.apply({display:true,question:q,media_playback:{...playing,position:7,revision:2}});
  assert.equal(video.currentTime,27);assert.equal(video.paused,false);
});

test('blocked autoplay exposes only one-click sound activation',async()=>{
  const h=harness({pathname:'/display'});
  h.run("sendMediaAction=async()=>{}");
  h.apply({display:true,question:{id:'m',media:{kind:'audio',url:'/audio.wav',start:0,end:30}},media_playback:{question:'m',playing:true,position:0,updated_at:0}});
  const [audio,controls]=h.node('media-content').children[0].children;
  audio.play=async()=>{const error=new Error('Blocked');error.name='NotAllowedError';throw error;};
  audio.emit('loadedmetadata');await Promise.resolve();await Promise.resolve();
  assert(!h.node('display-media-unlock').hidden);assert.equal(audio.paused,true);

  audio.play=async()=>{audio.paused=false;audio.emit('play');};
  await h.node('enable-display-media').onclick();
  assert(h.node('display-media-unlock').hidden);assert.equal(audio.paused,false);

});

test('display expansion and volume preserve the current media player',()=>{
  const h=harness({pathname:'/display'}),question={id:'q1',media:{kind:'video',url:'/video.mp4'}};
  const initial=h.apply({display:true,question,display_scene:'question',media_volume:.7});
  const wrapper=h.node('media-content').children[0],video=wrapper.children[0];video.emit('loadedmetadata');
  assert.equal(wrapper.children.length,1);assert.equal(video.controls,false);assert.equal(video.volume,.7);
  const plays=video.playCalls;
  h.apply({...initial,media_volume:0,media_expanded:true,version:initial.version+1,ui_version:initial.ui_version+1});
  assert.equal(h.ctx.document.body.dataset.mediaExpanded,'true');assert.equal(video.volume,0);
  assert.equal(h.node('media-content').children[0],wrapper);assert.equal(video.playCalls,plays);
  h.apply({display:true,question,media_expanded:true,paused:true,paused_at:1000});
  assert.equal(h.ctx.document.body.dataset.mediaExpanded,'false');
  h.apply({display:true,question,media_expanded:true,display_scene:'scores'});
  assert.equal(h.ctx.document.body.dataset.mediaExpanded,'false');
});

test('host controls image expansion and sends display volume',async()=>{
  const h=harness();h.run("auth.user.id='h';globalThis.sent=[];command=async(action,body)=>sent.push({action,body});api=async(path,body)=>{sent.push({action:body.action,body});return {...room,media_volume:body.volume,version:room.version+1,ui_version:room.ui_version+1}}");
  h.apply({question:{id:'q1',media:{kind:'image',url:'/picture.png'}}});
  assert(!h.node('display-media-expand').hidden);assert(h.node('display-media-toggle').hidden);
  assert(h.node('host-media-volume-label').hidden);
  await h.node('display-media-expand').onclick();assert.equal(h.ctx.sent[0].action,'media_expand');
  h.apply({question:{id:'q1',media:{kind:'audio',url:'/music.wav'}},media_volume:.3});
  assert(h.node('display-media-expand').hidden);assert(!h.node('host-media-volume-label').hidden);
  assert.equal(h.node('host-media-volume').value,30);
  h.node('host-media-volume').value=15;h.node('host-media-volume').oninput();await Promise.resolve();
  assert.equal(h.ctx.sent.at(-1).action,'media_volume');assert.equal(h.ctx.sent.at(-1).body.volume,.15);
});

test('hidden question images appear with the answer while hidden video retains audio',()=>{
  for(const kind of ['image','video']){
    const h=harness({pathname:'/display'}),question={id:'q1',media:{kind,url:'/file',show_in_question:false}};
    h.apply({display:true,question,display_scene:'question'});
    if(kind==='image')assert.equal(h.node('media-content').children.length,0);
    else {
      const audio=h.node('media-content').children[0].children[0];
      assert.equal(audio.tagName,'VIDEO');assert(audio.hidden);assert.equal(audio.controls,false);
    }
    assert(h.node('display-media-expand').hidden);
    h.apply({display:true,phase:'reveal',question,display_scene:'answer',media_playback:{question:'q1',mode:'full',playing:false,position:0}});
    const media=kind==='image'?h.node('media-content').children[0]:h.node('media-content').children[0].children[0];
    assert.equal(media.tagName,kind==='image'?'IMG':'VIDEO');assert(!media.hidden);
    h.apply({display:true,phase:'reveal',question,display_scene:'question',media_playback:{question:'q1',mode:'full',playing:false,position:0}});
    if(kind==='image')assert(h.node('media-content').hidden);
    else assert(h.node('media-content').children[0].children[0].hidden);
  }
});

test('last answer stays visible until host explicitly ends the round',async()=>{
  for(const role of ['host','player','display']){
    const h=harness();if(role==='host')h.run("auth.user.id='h'");
    const state={display:role==='display',phase:'reveal',display_scene:'answer',stage_complete:true,
      question:{id:'q1',text:'Last question',answer:'Answer'}};
    h.apply(state);
    assert(h.node('round-end').hidden);assert(!h.node('question').hidden);
    assert.equal(h.node('end-round').hidden,role!=='host');
    if(role==='host'){
      h.ctx.actions=[];h.run('command=async action=>actions.push(action)');
      await h.node('end-round').onclick();assert.equal(h.ctx.actions[0],'end_round');
    }
    h.apply({...state,display_scene:'round_end'});
    assert(!h.node('round-end').hidden);assert(h.node('question').hidden);assert(h.node('end-round').hidden);
  }
});

test('display sound permission cannot start media before host command',async()=>{
  const h=harness({pathname:'/display'}),question={id:'m',media:{kind:'audio',url:'/audio.wav'}};
  h.apply({display:true,question});
  const audio=h.node('media-content').children[0].children[0];audio.emit('loadedmetadata');
  await h.node('enable-display-media').onclick();
  assert.equal(audio.playCalls,0);assert(audio.paused);
  h.apply({display:true,question,media_playback:{question:'m',playing:true,position:0,updated_at:0,revision:1}});
  assert.equal(audio.playCalls,1);assert(!audio.paused);
});
