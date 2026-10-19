const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {randomUUID}=require('node:crypto');
const root=path.resolve(__dirname,'..');

function harness(doc){
  const nodes=new Map(),prompts=[];
  let approve=true;
  function element(){
    let value='',html='';const listeners={};
    return {hidden:false,disabled:false,dataset:{},options:[],classList:{toggle(){},add(){},remove(){}},
      get value(){return value;},set value(v){value=String(v);},
      get innerHTML(){return html;},set innerHTML(v){html=v;for(const m of v.matchAll(/id="([^"]+)"/g))if(!nodes.has(m[1]))nodes.set(m[1],element());this.options=[...v.matchAll(/<option value="([^"]*)"/g)].map(m=>({value:m[1]}));},
      querySelectorAll(){return [];},querySelector(){return null;},setAttribute(){},getAttribute(){return '';},removeAttribute(){},
      addEventListener(name,fn){(listeners[name]??=[]).push(fn);},emit(name){this['on'+name]?.();for(const fn of listeners[name]||[])fn();},
      focus(){},pause(){},replaceChildren(){},append(){},insertAdjacentElement(){},scrollIntoView(){},remove(){},textContent:''};
  }
  const html=fs.readFileSync(path.join(root,'builder/static/index.html'),'utf8');
  for(const m of html.matchAll(/id="([^"]+)"/g))nodes.set(m[1],element());
  const ctx={document:{getElementById:id=>nodes.get(id)||null,querySelectorAll:()=>[],createElement:element},
    window:{addEventListener(){},matchMedia:()=>({matches:false})},sessionStorage:{setItem(){},getItem(){},removeItem(){}},
    setTimeout(){},clearTimeout(){},fetch:()=>new Promise(()=>{}),crypto:{randomUUID},structuredClone,console,
    confirm:message=>{prompts.push(message);return approve;}};
  vm.createContext(ctx);
  for(const m of html.matchAll(/<script src="\/static\/([^?]+)\?/g))vm.runInContext(fs.readFileSync(path.join(root,'builder/static',m[1]),'utf8'),ctx);
  const run=code=>vm.runInContext(code,ctx);
  ctx.snapshot={id:'test',document:structuredClone(doc),published:true};run('state.busy=false;accept(snapshot)');
  return {node:id=>nodes.get(id),run,prompts,approve:v=>approve=v,
    doc:()=>JSON.parse(run('JSON.stringify(state.doc)')),
    input(id,value){const n=nodes.get(id);n.value=value;n.emit('input');},
    removeCategory(index){ctx.categoryButton={dataset:{categoryRemove:String(index)}};run("$('grid-category-list').onclick({target:{closest:s=>s==='[data-category-remove]'?categoryButton:null}})");}};
}
function document(){return {title:'Game',stages:[{id:'g',type:'grid',title:'Grid',categories:['Space','Other']},{id:'b',type:'blitz',title:'Blitz'}],
  rounds:[{id:'g1',stage:'g',type:'question',category:'Space',text:'A',answer:'A'},
    {id:'g2',stage:'g',type:'question',category:' space ',text:'B',answer:'B'},
    {id:'other',stage:'g',type:'question',category:'Other',text:'C',answer:'C'},
    {id:'b1',stage:'b',type:'question',category:'Space',text:'D',answer:'D'},
    {id:'e',stage:'b',type:'event',title:'Bonus',effect:{type:'shield',target:'all_players'}}]};}

test('display switch handles images and preserves legacy video sound settings',()=>{
  const h=harness(document());
  h.run("round().media={type:'image',file:'picture.png'};renderMediaFields()");
  assert(!h.node('media-display-option').hidden);assert(h.node('media-show-in-question').checked);
  h.node('media-show-in-question').checked=false;h.node('media-show-in-question').onchange();
  assert.equal(h.doc().rounds[0].media.show_in_question,false);
  h.run("round().media={type:'video',file:'clip.mp4',audio_only:true};renderMediaFields()");
  assert(!h.node('media-show-in-question').checked);
  h.node('media-show-in-question').checked=true;h.node('media-show-in-question').onchange();
  assert.equal(h.doc().rounds[0].media.show_in_question,true);
  assert(!('audio_only' in h.doc().rounds[0].media));
});

test('category deletion confirms and removes only its questions in this grid',()=>{
  const h=harness(document());
  h.approve(false);h.removeCategory(0);assert.equal(h.doc().rounds.length,5);
  h.approve(true);h.run("openCategoryQuestions('Space')");h.removeCategory(0);
  assert.deepEqual(h.doc().rounds.map(q=>q.id),['other','b1','e']);
  assert.deepEqual(h.doc().stages[0].categories,['Other']);
  assert.equal(h.run('round().id'),'other');assert.equal(h.run('editorNav.filter'),null);
  assert.match(h.prompts.at(-1),/Space.*\(2\)/);
});
test('deleting a category with no questions still requires confirmation',()=>{
  const doc=document();doc.stages[0].categories.push('Empty');const h=harness(doc);
  h.approve(false);h.removeCategory(2);assert.equal(h.doc().stages[0].categories.length,3);
  h.approve(true);h.removeCategory(2);assert.equal(h.doc().rounds.length,5);
});
test('category deletion preserves selection when earlier questions shift its index',()=>{
  const h=harness(document());h.run('state.index=2;renderRound()');h.removeCategory(0);
  assert.equal(h.run('round().id'),'other');assert.equal(h.run('state.index'),0);
});
test('round deletion removes questions and events after confirmation',()=>{
  const h=harness(document());h.run('selectStage(1)');h.approve(false);h.node('stage-delete').onclick();assert.equal(h.doc().stages.length,2);
  h.approve(true);h.node('stage-delete').onclick();
  assert.deepEqual(h.doc().rounds.map(q=>q.id),['g1','g2','other']);assert.equal(h.doc().stages.length,1);
  assert.match(h.prompts.at(-1),/Blitz/);
});
test('last round can be deleted, saved as empty draft, reopened and replaced',()=>{
  const doc={title:'Empty',stages:[{id:'b',title:'Last',type:'blitz'}],rounds:[{id:'q',stage:'b',type:'question'}]};
  const h=harness(doc);h.node('stage-delete').onclick();
  assert.equal(h.doc().stages.length,0);assert.equal(h.doc().rounds.length,0);
  assert(!h.node('no-stages').hidden);assert(h.node('add-question').disabled);
  h.run('accept({id:"test",document:state.doc})');assert.equal(h.doc().stages.length,0);
  h.node('new-stage-type').value='blitz';h.node('add-stage').onclick();
  assert.equal(h.doc().stages.length,1);assert.equal(h.doc().rounds.length,1);assert(h.node('no-stages').hidden);
});
test('game defaults affect inherited questions and preview while retaining exceptions',()=>{
  const doc=document();doc.settings={time_limit:30,points:200};doc.rounds[1].time_limit=75;doc.rounds[1].points=0;
  const h=harness(doc);
  assert.equal(h.node('time-limit').value,'');assert.match(h.node('time-limit').placeholder,/30/);
  h.input('game-time-limit','50');h.input('game-points','300');
  assert.match(h.node('preview-content').innerHTML,/300.*50/);assert.equal(h.doc().rounds[1].time_limit,75);
  h.run('state.index=1;renderRound()');assert.equal(h.node('time-limit').value,'75');assert.equal(h.node('points').value,'0');
  h.input('time-limit','');h.input('points','');
  assert(!('time_limit' in h.doc().rounds[1]));assert(!('points' in h.doc().rounds[1]));
  assert.match(h.node('preview-content').innerHTML,/300.*50/);
  h.node('add-question').onclick();assert(!('time_limit' in h.doc().rounds[2]));
});
test('reset all question times confirms and keeps grid prices',()=>{
  const doc=document();doc.rounds[0].time_limit=20;doc.rounds[0].points=500;
  doc.rounds[1].time_limit=60;doc.rounds[1].points=1000;const h=harness(doc);
  h.approve(false);h.node('reset-question-times').onclick();assert.equal(h.doc().rounds[0].time_limit,20);
  h.approve(true);h.node('reset-question-times').onclick();
  assert(h.doc().rounds.every(q=>!('time_limit' in q)));assert.equal(h.doc().rounds[0].points,500);assert.equal(h.doc().rounds[1].points,1000);
});
test('busy editor cannot delete or change global settings',()=>{
  const h=harness(document());h.run('state.busy=true');h.node('stage-delete').onclick();h.removeCategory(0);h.input('game-time-limit','99');
  assert.equal(h.doc().rounds.length,5);assert(!h.doc().settings);assert.equal(h.prompts.length,0);
});
test('invalid defaults open game settings and missing rounds open round creation',()=>{
  const h=harness(document());
  h.run('setPublicationIssues([{field:"settings.time_limit",stage_index:null,item_index:null,message:"Invalid",location:"Game"}],true)');
  assert.equal(h.run('editorNav.gameTab'),'info');
  assert.equal(h.run('issueField(publicationValidation.issues[0])'),'game-time-limit');
  h.run('state.doc.stages=[];state.doc.rounds=[];state.index=-1;setPublicationIssues([{field:"stages",stage_index:null,item_index:null,message:"Add round",location:"Game"}],true)');
  assert.equal(h.run('editorNav.gameTab'),'rounds');assert(h.node('add-stage-panel').open);
});
