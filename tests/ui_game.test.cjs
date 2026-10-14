// Run with: node --test tests/ui_game.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'..');

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
  const ctx={document:{getElementById(id){assert(nodes.has(id),'Missing DOM ID: '+id);return nodes.get(id);},querySelectorAll(){return [];},createElement:element,addEventListener(){},body:{dataset:{}}},
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

test('intro survives reaction updates without restarting crawl',()=>{
  const h=harness(),state=h.apply({phase:'intro',question:null,active:null,intro_started_at:1000,intro_until:1014});
  assert(!h.node('grid-intro').hidden);assert(h.node('question-board').hidden);assert(h.node('question').hidden);
  const writes=h.node('theme-crawl').writes;
  h.apply({...state,version:state.version+1,reactions:[{id:1,time:1000,emoji:'👏'}]});
  assert.equal(h.node('theme-crawl').writes,writes);
});

test('ceremony reveals lower places then third, second and first on all player screens',()=>{
  const h=harness();
  const players=[{id:'h',name:'Host',score:0},...['First','Second','Third','Fourth','Last'].map((name,i)=>({id:'p'+i,name,score:500-i*100}))];
  h.apply({phase:'finished',question:null,active:null,finished_at:1000,players});
  assert.match(h.node('final-results').innerHTML,/Last.*Fourth/s);
  assert.doesNotMatch(h.node('final-results').innerHTML,/First|Second|Third/);
  assert(h.node('scoreboard').hidden);assert(h.node('another').hidden);
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
  assert.match(h.node('my-effect-list').innerHTML,/🪤.*Половина награды.*2 вопроса.*включая текущий/s);
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

test('audio timeline is relative to clip, seeks inside it and restarts at its beginning',async()=>{
  const h=harness({pathname:'/display'});
  h.run("sendMediaAction=async(action,position,duration)=>{room.media_playback={question:room.question.id,playing:action==='media_play',position,duration,updated_at:0,revision:1};}");
  h.apply({display:true,question:{id:'music',text:'?',media:{kind:'audio',url:'/song.mp3',start:60,end:90}}});
  const wrapper=h.node('media-content').children[0];
  const [audio,controls,seek,time]=wrapper.children;
  audio.emit('loadedmetadata');
  assert.equal(audio.controls,false);assert.equal(audio.hidden,true);
  assert.equal(audio.currentTime,60);assert.equal(seek.max,30);
  assert.equal(time.textContent,'0:00 / 0:30');
  assert.equal(controls.children.length,1);assert.equal(audio.paused,false);
  await controls.children[0].onclick();assert.equal(audio.paused,true);assert.equal(controls.children[0].textContent,'▶ Воспроизвести');
  seek.value=12;seek.oninput();assert.equal(audio.currentTime,72);
  assert.equal(time.textContent,'0:12 / 0:30');
  audio.currentTime=90;
  await controls.children[0].onclick();assert.equal(audio.currentTime,60);assert.equal(audio.paused,false);
  audio.currentTime=91;audio.emit('timeupdate');assert.equal(audio.currentTime,90);assert.equal(audio.paused,true);
  audio.currentTime=50;audio.emit('seeking');assert.equal(audio.currentTime,60);
});

test('audio clips clamp to actual file length and reject missing intervals',()=>{
  const h=harness({pathname:'/display'});
  h.apply({display:true,question:{id:'music',media:{kind:'audio',url:'/song.mp3',start:150,end:300}}});
  let [audio,,seek,time]=h.node('media-content').children[0].children;
  audio.emit('loadedmetadata');assert.equal(seek.max,50);assert.equal(time.textContent,'0:00 / 0:50');
  h.apply({display:true,question:{id:'bad',media:{kind:'audio',url:'/song.mp3',start:250}}});
  [audio,,seek]=h.node('media-content').children[0].children;
  audio.emit('loadedmetadata');assert(seek.disabled);
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
  assert(h.node('scoreboard').hidden);assert.equal(h.node('players').innerHTML,'');
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
    assert(h.node('scoreboard').hidden,phase);assert(h.node('display-preview').hidden,phase);
  }
  h.apply({display:true,phase:'board',question:null,active:null});
  assert(!h.node('question-board').hidden);assert(h.node('scoreboard').hidden);
});

test('display retains dedicated round scores and awards; host keeps their roster',()=>{
  const h=harness({pathname:'/display'});
  h.apply({display:true,phase:'reveal',stage_complete:true,scores_visible:true});
  assert(!h.node('round-scores').hidden);assert(h.node('question').hidden);assert(h.node('scoreboard').hidden);
  assert.match(h.node('round-results').innerHTML,/Player/);
  h.apply({display:true,phase:'finished',question:null,finished_at:1000});
  assert(!h.node('finished').hidden);assert(h.node('display-preview').hidden);assert(h.node('scoreboard').hidden);
  const host=harness();host.run("auth.user.id='h'");host.apply({phase:'lobby',question:null});
  assert(!host.node('scoreboard').hidden);assert(!host.node('lobby').hidden);assert(host.node('display-preview').hidden);
});

test('player never loads audio or video; host gets remote controls and images remain visible',async()=>{
  for(const kind of ['audio','video']){
    const player=harness();player.apply({question:{id:'m',media:{kind,url:'/private-media'}}});
    assert(player.node('media-content').hidden);assert.equal(player.node('media-content').children.length,0);
    assert(player.node('host-media-controls').hidden);
    const host=harness();host.run("auth.user.id='h'");host.ctx.calls=[];
    host.run('sendMediaAction=async action=>calls.push(action)');
    host.apply({question:{id:'m',media:{kind,url:'/private-media'}}});
    assert(!host.node('host-media-controls').hidden);assert.equal(host.node('media-content').children.length,0);
    await host.node('display-media-play').onclick();await host.node('display-media-pause').onclick();
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
  assert.equal(controls.children[0].textContent,'Ⅱ Пауза');
  const plays=video.playCalls;
  h.apply({...state,version:state.version+1,reactions:[]});assert.equal(video.playCalls,plays);
  h.apply({display:true,question:q,media_playback:{...playing,playing:false,position:7,revision:1}});
  assert.equal(video.currentTime,27);assert.equal(video.paused,true);assert.equal(controls.children[0].textContent,'▶ Воспроизвести');
  h.apply({display:true,question:q,media_playback:{...playing,position:7,revision:2}});
  assert.equal(video.currentTime,27);assert.equal(video.paused,false);
});

test('blocked autoplay exposes one-click sound activation and keeps the real play/pause label',async()=>{
  const h=harness({pathname:'/display'});
  h.run("sendMediaAction=async()=>{}");
  h.apply({display:true,question:{id:'m',media:{kind:'audio',url:'/audio.wav',start:0,end:30}}});
  const [audio,controls]=h.node('media-content').children[0].children;
  audio.play=async()=>{const error=new Error('Blocked');error.name='NotAllowedError';throw error;};
  audio.emit('loadedmetadata');await Promise.resolve();await Promise.resolve();
  assert(!h.node('display-media-unlock').hidden);assert.equal(audio.paused,true);
  assert.equal(controls.children[0].textContent,'▶ Воспроизвести');
  audio.play=async()=>{audio.paused=false;audio.emit('play');};
  await h.node('enable-display-media').onclick();
  assert(h.node('display-media-unlock').hidden);assert.equal(audio.paused,false);
  assert.equal(controls.children[0].textContent,'Ⅱ Пауза');
});
