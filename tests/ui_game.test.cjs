// Run with: node --test tests/ui_game.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.resolve(__dirname,'..');

function harness() {
  let clock=1000000;
  class Clock extends Date {static now(){return clock;}}
  function element(){
    let html='';
    return {hidden:false,dataset:{},style:{setProperty(){}},value:'',options:[],children:[],writes:0,textContent:'',previousElementSibling:{},
      get innerHTML(){return html;},set innerHTML(value){html=value;this.writes++;},
      querySelectorAll(){return [];},querySelector(){return null;},setAttribute(){},addEventListener(){},
      replaceChildren(){this.children=[];},append(node){this.children.push(node);},remove(){},
    };
  }
  const nodes=new Map([...fs.readFileSync(path.join(root,'static/index.html'),'utf8').matchAll(/id="([^"]+)"/g)].map(m=>[m[1],element()]));
  const ctx={document:{getElementById(id){assert(nodes.has(id),'Missing DOM ID: '+id);return nodes.get(id);},querySelectorAll(){return [];},createElement:element,addEventListener(){},body:{dataset:{}}},
    window:{addEventListener(){},matchMedia(){return {matches:false};}},sessionStorage:{getItem(){return null;},setItem(){},removeItem(){}},location:{search:''},URLSearchParams,
    fetch:()=>new Promise(()=>{}),setInterval(){},setTimeout(){},clearTimeout(){},Date:Clock,console};
  vm.createContext(ctx);
  for(const file of ['experience.js','app.js'])vm.runInContext(fs.readFileSync(path.join(root,'static',file),'utf8'),ctx);
  vm.runInContext("auth={user:{id:'p',name:'Player'}}",ctx);
  let version=0;
  const base={code:'ABC234',host:'h',players:[{id:'h',name:'Host',score:0},{id:'p',name:'Player',score:0}],phase:'question',stage:{id:'g',title:'Grid',type:'grid',categories:['Space']},stages:[{id:'g',type:'grid'}],stage_count:1,stage_number:1,question_count:2,question_number:1,round_count:2,used:[],answered_ids:[],answers:{},question:{id:'q1',category:'Space',text:'Question',value:100,seconds:45},active:'q1',deadline:1045,chooser:'h',board:[{id:'q2',category:'Space',value:200,used:false}],can_pick:false};
  const apply=patch=>{ctx.snapshot={...base,version:++version,ui_version:version,server_time:clock/1000,...patch};vm.runInContext('apply(snapshot)',ctx);return ctx.snapshot;};
  const node=id=>nodes.get(id);
  return {ctx,apply,node,run:code=>vm.runInContext(code,ctx),advance:ms=>{clock+=ms;vm.runInContext('tick()',ctx);}};
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
