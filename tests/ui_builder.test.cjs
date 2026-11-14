const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {randomUUID}=require('node:crypto');
const root=path.resolve(__dirname,'..');

test('media preload setting defaults on, persists in the document and respects busy state',()=>{
  const h=harness(document());
  assert.equal(h.node('game-preload-media').value,'on');
  h.input('game-preload-media','off');assert.equal(h.doc().settings.preload_media,false);
  h.run('renderGameSettings()');assert.equal(h.node('game-preload-media').value,'off');
  h.run('state.busy=true');h.input('game-preload-media','on');assert.equal(h.doc().settings.preload_media,false);
});

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
      open:false,showModal(){this.open=true;},close(){this.open=false;this.emit('close');},
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
test('round penalty settings remain independent across round changes',()=>{
  const h=harness(document());
  assert.equal(h.node('stage-answer-penalties').value,'on');
  h.input('stage-answer-penalties','off');
  assert.equal(h.doc().stages[0].answer_penalties,false);
  assert.equal(h.doc().stages[0].trap_penalties,undefined);
  h.run('selectStage(1)');
  assert.equal(h.node('stage-answer-penalties').value,'on');
  h.input('stage-trap-penalties','off');
  h.run('selectStage(0)');
  assert.equal(h.node('stage-answer-penalties').value,'off');
  assert.equal(h.node('stage-trap-penalties').value,'on');
});
function document(){return {title:'Game',stages:[{id:'g',type:'grid',title:'Grid',categories:['Space','Other']},{id:'b',type:'blitz',title:'Blitz'}],
  rounds:[{id:'g1',stage:'g',type:'question',category:'Space',text:'A',answer:'A'},
    {id:'g2',stage:'g',type:'question',category:' space ',text:'B',answer:'B'},
    {id:'other',stage:'g',type:'question',category:'Other',text:'C',answer:'C'},
    {id:'b1',stage:'b',type:'question',category:'Space',text:'D',answer:'D'},
    {id:'e',stage:'b',type:'event',title:'Bonus',effect:{type:'shield',target:'all_players'}}]};}

function serverState(){return {available:true,metrics:{cpu_percent:25,cpu_count:2,memory:{used:1024**3,total:2*1024**3},disk:{used:1024**3,total:10*1024**3},uptime:90000},services:{'rat-race-web.service':'active'},versions:{app:{current:{version:'0.5.0',build:'a'.repeat(40)},previous:{version:'0.4.0',build:'b'.repeat(40)}}}};}

test('application settings show server statistics and disable unavailable or running operations',()=>{
  const h=harness(document());
  h.run('state.busy=false');
  h.run('globalThis.status='+JSON.stringify(serverState())+';renderServerStatus(status)');
  assert.match(h.node('server-stats').innerHTML,/25%/);
  assert.match(h.node('server-versions').innerHTML,/0.5.0.*0.4.0/);
  assert(!h.node('server-update').disabled);assert(!h.node('server-rollback').disabled);
  h.run("renderServerStatus({...status,job:{action:'update',status:'running',log:'Checking release'}})");
  assert(h.node('server-update').disabled);assert(h.node('server-rollback').disabled);
  assert.equal(h.node('server-job-log').textContent,'Checking release');
  h.run('status.versions.app.previous=null;renderServerStatus(status)');
  assert(!h.node('server-update').disabled);assert(h.node('server-rollback').disabled);
  h.run("renderServerStatus({available:false,message:'Linux only'})");
  assert(h.node('server-update').disabled);assert.equal(h.node('server-status-message').textContent,'Linux only');
});

test('server update saves the draft first and blocks repeat clicks while awaiting response',async()=>{
  const h=harness(document());
  h.run('state.busy=false;state.dirty=true;renderServerStatus('+JSON.stringify(serverState())+')');
  h.run("globalThis.calls=[];save=async()=>{calls.push('save');state.dirty=false;};api=async(path,method,body)=>{calls.push(body.action);return new Promise(resolve=>globalThis.complete=resolve);}");
  const first=h.node('server-update').onclick();
  await new Promise(setImmediate);
  await h.node('server-update').onclick();
  assert.deepEqual(JSON.parse(h.run('JSON.stringify(calls)')),['save','update']);
  h.run("complete({job:{id:'job',action:'update',status:'running'}})");await first;
  assert(h.node('server-update').disabled);
  assert(h.prompts[0].includes('0.5.0'));
});

test('cancelled rollback and failed draft save never start server changes',async()=>{
  const h=harness(document());
  h.run('state.busy=false;renderServerStatus('+JSON.stringify(serverState())+');globalThis.calls=[];api=async()=>calls.push("request")');
  h.approve(false);await h.node('server-rollback').onclick();
  assert.equal(h.run('calls.length'),0);
  h.approve(true);h.run('state.dirty=true;save=async()=>{throw new Error("Save conflict")};loadServerStatus=async()=>{}');
  await h.node('server-update').onclick();
  assert.equal(h.run('calls.length'),0);
  assert.equal(h.node('notice-text').textContent,'Save conflict');
  assert.equal(h.run('state.busy'),false);
});

test('stale statistics cannot replace a newly launched server job',async()=>{
  const h=harness(document());
  h.run('state.busy=false;renderServerStatus('+JSON.stringify(serverState())+');$("app-settings-dialog").showModal();api=()=>new Promise(resolve=>globalThis.oldStatus=resolve)');
  const pending=h.run('loadServerStatus()');
  h.run("api=async()=>({job:{id:'new',action:'rollback',status:'running'}})");
  await h.node('server-rollback').onclick();
  h.run('oldStatus('+JSON.stringify(serverState())+')');await pending;
  assert.equal(h.run('serverSnapshot.job.id'),'new');
  assert(h.node('server-update').disabled);
});

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
  assert.match(h.node('preview-content').innerHTML,/300/);assert.equal(h.doc().rounds[1].time_limit,75);
  h.run('state.index=1;renderRound()');assert.equal(h.node('time-limit').value,'75');assert.equal(h.node('points').value,'0');
  h.input('time-limit','');h.input('points','');
  assert(!('time_limit' in h.doc().rounds[1]));assert(!('points' in h.doc().rounds[1]));
  assert.match(h.node('preview-content').innerHTML,/300/);
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

test('new questions append to their stage regardless of selection and filters',()=>{
  const h=harness(document());h.run("openCategoryQuestions('Space');state.index=0");
  h.node('add-question').onclick();
  assert.deepEqual(h.doc().rounds.slice(0,3).map(q=>q.id),['g1','g2','other']);
  assert.equal(h.doc().rounds[3].stage,'g');assert.equal(h.run('state.index'),3);
  assert.equal(h.doc().rounds[4].id,'b1');
});
test('question movement swaps neighbors within a stage and preserves selection',()=>{
  const h=harness(document());h.run('state.index=1;move(1)');
  assert.deepEqual(h.doc().rounds.map(q=>q.id),['g1','other','g2','b1','e']);
  assert.equal(h.run('round().id'),'g2');h.run('move(1)');
  assert.equal(h.run('state.index'),2);h.run('move(-1)');
  assert.deepEqual(h.doc().rounds.map(q=>q.id),['g1','g2','other','b1','e']);
});
test('multi-file upload keeps question and answer files separate and resets replaced clips',async()=>{
  const h=harness(document());h.run("uploadEditorMedia=async()=>({type:'video',file:'media/'+(++uploadCount)+'.mp4'});uploadCount=0");
  await h.run("uploadFiles([{name:'one.mp4',size:10},{name:'two.mp4',size:10}])");
  await h.run("uploadFiles([{name:'answer.mp4',size:10}],{answer:true})");
  let q=h.doc().rounds[0];assert.equal(q.media.file,'media/1.mp4');assert.equal(q.attachments.length,2);
  assert(!q.attachments[0].answer);assert(q.attachments[1].answer);
  h.run('round().media.start=25;round().media.end=30');
  await h.run("uploadFiles([{name:'replacement.mp4',size:10}],{primary:true})");
  q=h.doc().rounds[0];assert.equal(q.media.start,0);assert.equal(q.media.end,undefined);assert.equal(q.attachments.length,2);
  await h.run("uploadFiles([{name:'replacement.mp4',size:10}],{replace:1})");
  assert(h.doc().rounds[0].attachments[1].answer);
});
test('each upload zone accepts drops explicitly for both initial upload and replacement',()=>{
  const h=harness(document());
  for(const id of ['primary-drop','question-drop','answer-drop','attachment-list']){
    assert.equal(typeof h.node(id).ondragover,'function');assert.equal(typeof h.node(id).ondrop,'function');
  }
});

test('creating a game opens its first question after the asynchronous request',async()=>{
  const h=harness(document());h.node('create-dialog').close=()=>{};h.node('new-title').value='New';
  h.run("api=async()=>({id:'new',document:{title:'New',stages:[{id:'first',type:'blitz',title:'First'}],rounds:[]}});refresh=async()=>{}");
  await h.node('create-form').onsubmit();
  assert.equal(h.doc().rounds.length,1);assert.equal(h.run('round().stage'),'first');assert(h.run('state.dirty'));
});
test('a new empty stage at the question limit can be saved',()=>{
  const doc=document();doc.rounds=Array.from({length:100},(_,i)=>({...doc.rounds[0],id:'q'+i}));
  const h=harness(doc);h.node('new-stage-type').value='blitz';h.node('add-stage').onclick();
  assert.equal(h.doc().stages.length,3);assert.equal(h.doc().rounds.length,100);assert(h.run('state.dirty'));
  assert(!h.node('save').disabled);
});
test('movement in a category filter swaps visible questions without touching hidden questions',()=>{
  const doc=document();[doc.rounds[1],doc.rounds[2]]=[doc.rounds[2],doc.rounds[1]];
  const h=harness(doc);h.run("openCategoryQuestions('Space');move(1)");
  assert.deepEqual(h.doc().rounds.slice(0,3).map(q=>q.id),['g2','other','g1']);
  assert.equal(h.run('round().id'),'g1');assert(h.node('move-down').disabled);
  assert.match(h.node('round-list').innerHTML,/round-number">03/);
});
test('leaving the editor pauses every preview attachment',()=>{
  const h=harness(document());h.run("previewPlayers=[{paused:false,pause(){this.paused=true}},{paused:false,pause(){this.paused=true}}];$('preview-media').querySelectorAll=()=>previewPlayers");
  h.run('pauseClipEditor()');assert(h.run('previewPlayers.every(p=>p.paused)'));
});

test('invalid imported attachment entries stay editable until validation',()=>{
  const doc=document();doc.rounds[0].attachments=[null,{type:'video'},{type:'image',file:42}];
  const h=harness(doc);assert(h.node('attachment-list').innerHTML.includes('Файл не выбран'));
  assert.equal(h.doc().rounds[0].attachments.length,3);
});

test('answer-only attachments are visible in material status and question list',()=>{
  const doc=document();doc.rounds[0].attachments=[{type:'image',file:'media/answer.png',answer:true}];
  const h=harness(doc);assert.match(h.node('material-status').textContent,/1 файл/);
  assert.match(h.node('round-list').innerHTML,/МЕДИА/);
});
