const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const show = (id, visible) => { $(id).hidden = !visible; };
const state = {games:[], snapshot:null, doc:null, index:-1, dirty:false, busy:false};

function notice(message='', type='info') {
  $('notice').textContent=message; $('notice').dataset.type=type; show('notice',!!message);
}
function loginScreen() {show('login-panel',true);show('studio',false);show('account-actions',false);}
async function api(path, method='GET', data) {
  const response=await fetch('/api'+path, {method,headers:{'X-Builder-Request':'1',...(data!==undefined?{'Content-Type':'application/json'}:{})},...(data!==undefined?{body:JSON.stringify(data)}:{})});
  const result=await response.json();
  if(!response.ok) {if(response.status===401)loginScreen();throw new Error(typeof result.detail==='string'?result.detail:'Проверь заполненные поля.');}
  return result;
}
function guarded(fn) {
  return async event => {
    event?.preventDefault(); if(state.busy)return;
    state.busy=true;notice();updateActions();
    try {await fn(event);} catch(error) {notice(error.message||'Не удалось связаться с сервером.','error');}
    finally {state.busy=false;updateActions();}
  };
}
function updateActions() {
  for(const id of ['save','publish','export','reload-published','new-game','add-question','add-event','refresh','logout','move-up','move-down','duplicate-round','remove-round','remove-media'])$(id).disabled=state.busy;
  $('save').disabled=state.busy||!state.dirty;
  $('add-question').disabled=$('add-event').disabled=state.busy||(state.doc?.rounds.length??0)>=100;
  $('move-up').disabled=state.busy||state.index<=0;
  $('move-down').disabled=state.busy||state.index<0||state.index>=((state.doc?.rounds.length??0)-1);
  $('media-file').disabled=state.busy;
  $('import-json').disabled=state.busy;
  // Freeze editable fields while saving so a delayed response cannot replace new typing.
  for(const input of $('editor').querySelectorAll('input:not([type=file]), textarea, select'))input.disabled=state.busy;
  const message=state.dirty?'Есть несохранённые изменения':state.snapshot?.dirty?'Черновик сохранён':'Опубликована';
  $('save-status').textContent=message;$('save-status').dataset.dirty=state.dirty;
}
function markDirty() {state.dirty=true;updateActions();renderRounds();}
function canLeave() {return !state.dirty||confirm('В игре есть несохранённые изменения. Продолжить без сохранения?');}
function round() {return state.doc?.rounds[state.index];}
function id() {return encodeURIComponent(state.snapshot.id);}
function roundId() {return 'r-'+crypto.randomUUID().replaceAll('-','').slice(0,16);}

function renderLibrary() {
  const search=$('search').value.trim().toLowerCase();
  const filtered=state.games.filter(g=>(g.title+' '+g.description).toLowerCase().includes(search));
  $('game-list').innerHTML=filtered.length?filtered.map(g=>`<button class="game-card ${g.id===state.snapshot?.id?'active':''}" data-game="${esc(g.id)}"><strong>${esc(g.title)}</strong><small>${g.questions} вопросов · ${g.rounds} раундов</small><span class="game-badge ${g.error?'error':''}">${g.error?'Ошибка пакета':g.dirty?'Есть черновик':g.published?'В библиотеке':'Новая игра'}</span></button>`).join(''):`<p class="library-empty">${search?'Ничего не найдено.':'Пока нет игр. Начни с новой.'}</p>`;
}
async function refresh() {state.games=await api('/games');renderLibrary();}
function accept(snapshot, selected=0) {
  state.snapshot=snapshot;state.doc=structuredClone(snapshot.document);state.dirty=false;
  if(!Array.isArray(state.doc.rounds))state.doc.rounds=[];
  state.index=state.doc.rounds.length?Math.min(selected,state.doc.rounds.length-1):-1;
  $('game-title').value=state.doc.title||'';$('game-description').value=state.doc.description||'';
  $('editor-title').textContent=state.doc.title||'Без названия';
  show('empty',false);show('editor',true);show('reload-published',snapshot.published);
  renderLibrary();renderRounds();renderRound();updateActions();
}
async function openGame(gameId) {
  if(!canLeave())return;
  accept(await api('/games/'+encodeURIComponent(gameId)+'/open','POST'));
}
function renderRounds() {
  if(!state.doc)return;
  const questions=state.doc.rounds.filter(q=>q?.type==='question').length;
  $('round-count').textContent=questions+' вопросов · '+state.doc.rounds.length+' раундов';
  show('no-rounds',!state.doc.rounds.length);
  $('round-list').innerHTML=state.doc.rounds.map((q,i)=>`<li><button class="${i===state.index?'selected':''}" data-round="${i}" aria-pressed="${i===state.index}"><span class="round-number">${String(i+1).padStart(2,'0')}</span><span class="round-name"><small>${q.type==='event'?'✳ СОБЫТИЕ':'ВОПРОС'}${q.media?' · МЕДИА':''}</small>${esc(q.type==='event'?q.title||'Новое событие':q.text||'Новый вопрос')}</span></button></li>`).join('');
}
function renderRound() {
  const q=round();show('round-empty',!q);show('round-details',!!q);if(!q)return;
  const event=q.type==='event';show('question-fields',!event);show('event-fields',event);
  $('round-type').textContent=event?'СОБЫТИЕ':'ВОПРОС';$('round-heading').textContent='Раунд '+(state.index+1);
  if(event) {
    $('event-title').value=q.title||'';$('event-text').value=q.text||'';
    $('effect-type').value=q.effect?.type||'random_buff';$('effect-target').value=q.effect?.target||'random_player';$('effect-duration').value=q.effect?.questions??1;
    renderEffect();
  } else {
    $('question-text').value=q.text||'';$('answer').value=q.answer||'';
    $('accepted-answers').value=Array.isArray(q.accepted_answers)?q.accepted_answers.join('\n'):'';$('points').value=q.points??100;$('time-limit').value=q.time_limit??45;$('category').value=q.category||'';
    $('media-type').value=q.media?.type||'';renderMediaFields();
  }
  renderPreview();updateActions();
}
function renderEffect() {
  $('effect-explanation').textContent=$('effect-type').value==='random_buff'?'Случайно выбирается двойная награда или защита от штрафа. Новое событие заменяет предыдущий эффект.':'Случайно выбирается половина награды или двойной штраф. Новое событие заменяет предыдущий эффект.';
}
function renderMediaFields() {
  const m=round()?.media,type=m?.type||'';
  show('media-fields',!!type);show('clip-fields',type==='audio'||type==='video');show('attached-file',!!m?.file);
  $('file-name').textContent=typeof m?.file==='string'?m.file.split('/').pop():'';
  $('media-file').value='';$('media-file').accept=type==='image'?'.png,.jpg,.jpeg,.gif,.webp':type==='audio'?'.mp3,.wav,.ogg,.m4a':'.mp4,.webm';
  $('upload-label').textContent=m?.file?'Заменить материал':'Выбрать файл';
  $('clip-start').value=m?.start??0;$('clip-end').value=m?.end??'';
}
function mediaURL(file) {return '/api/games/'+id()+'/media?file='+encodeURIComponent(file);}
function renderPreview() {
  const q=round();if(!q)return;
  const box=$('preview-content');
  if(q.type==='event') {
    box.innerHTML=`<div class="preview-meta"><span>СОБЫТИЕ</span><span>${esc(q.effect?.questions??1)} вопросов</span></div><h3>${esc(q.title||'Название события')}</h3><p>${esc(q.text||'Описание события появится здесь.')}</p><div class="preview-answer">${q.effect?.type==='random_debuff'?'Ослабление':'Усиление'} · ${q.effect?.target==='all_players'?'всем игрокам':'случайному игроку'}</div>`;
    return;
  }
  box.innerHTML=`<div class="preview-meta"><span>${esc(q.category||'ВОПРОС')}</span><span>${esc(q.points??100)} очков · ${esc(q.time_limit??45)} сек.</span></div><h3>${esc(q.text||'Текст вопроса появится здесь.')}</h3><div id="preview-media"></div><div class="preview-answer">Ответ для ведущего: <strong>${esc(q.answer||'Ещё не указан')}</strong></div>`;
  const m=q.media;if(typeof m?.file!=='string'||!m.file||!['image','audio','video'].includes(m.type))return;
  const node=document.createElement(m.type==='image'?'img':m.type);node.src=mediaURL(m.file);
  node.onerror=()=>{$('preview-media')?.replaceChildren(Object.assign(document.createElement('p'),{textContent:'Материал не найден. Загрузи файл для этого вопроса.'}));};
  if(m.type==='image')node.alt='Материал к вопросу';
  else {
    node.controls=true;node.preload='metadata';if(m.type==='video')node.setAttribute('playsinline','');
    const start=m.start||0,end=m.end;
    node.addEventListener('loadedmetadata',()=>{if(start<node.duration)node.currentTime=start;});
    node.addEventListener('play',()=>{if(node.currentTime<start||(end!=null&&node.currentTime>=end))node.currentTime=start;});
    node.addEventListener('timeupdate',()=>{if(end!=null&&node.currentTime>=end)node.pause();});
  }
  $('preview-media').append(node);
}
function bind(field, getter, setter) {
  $(field).addEventListener('input',()=>{if(!round())return;setter(round(),getter($(field).value));markDirty();renderPreview();});
}
for(const [field,key] of [['question-text','text'],['answer','answer'],['category','category'],['event-title','title'],['event-text','text']])bind(field,v=>v,(q,v)=>q[key]=v);
for(const [field,key] of [['points','points'],['time-limit','time_limit']])bind(field,Number,(q,v)=>q[key]=v);
bind('accepted-answers',v=>v.split('\n').map(s=>s.trim()).filter(Boolean),(q,v)=>q.accepted_answers=v);
for(const [field,key] of [['effect-type','type'],['effect-target','target'],['effect-duration','questions']])bind(field,v=>field==='effect-duration'?Number(v):v,(q,v)=>{q.effect??={};q.effect[key]=v;renderEffect();});
for(const [field,key] of [['clip-start','start'],['clip-end','end']])bind(field,v=>v===''?null:Number(v),(q,v)=>{if(q.media)q.media[key]=key==='start'?v??0:v;});
$('media-type').onchange=()=>{if(!round())return;const type=$('media-type').value;if(type)round().media={type,file:'',start:0};else delete round().media;markDirty();renderMediaFields();renderPreview();};
$('remove-media').onclick=()=>{delete round().media;$('media-type').value='';markDirty();renderMediaFields();renderPreview();};
$('media-file').onchange=guarded(async()=>{
  const file=$('media-file').files[0];if(!file)return;if(file.size>25*1024*1024)throw new Error('Файл должен быть не больше 25 МБ.');
  const q=round(),type=q.media.type;const response=await fetch('/api/games/'+id()+'/media?kind='+type,{method:'POST',headers:{'X-Builder-Request':'1'},body:file});
  const result=await response.json();if(!response.ok)throw new Error(result.detail||'Не удалось загрузить материал.');
  q.media={...q.media,type:result.type,file:result.file};markDirty();renderMediaFields();renderPreview();notice('Материал загружен. Сохрани черновик, чтобы сохранить его в вопросе.');
});
for(const [field,key] of [['game-title','title'],['game-description','description']])$(field).oninput=()=>{state.doc[key]=$(field).value;$('editor-title').textContent=state.doc.title||'Без названия';markDirty();};

function addRound(type) {
  if(state.doc.rounds.length>=100)return;
  const q=type==='event'?{id:roundId(),type,title:'',text:'',effect:{type:'random_buff',target:'random_player',questions:1}}:{id:roundId(),type,text:'',answer:'',points:100,time_limit:45,accepted_answers:[]};
  state.doc.rounds.splice(state.index+1,0,q);state.index++;markDirty();renderRound();
}
$('add-question').onclick=()=>addRound('question');$('add-event').onclick=()=>addRound('event');
$('round-list').onclick=event=>{const button=event.target.closest('[data-round]');if(!button||state.busy)return;state.index=Number(button.dataset.round);renderRounds();renderRound();};
function move(delta) {const target=state.index+delta;if(target<0||target>=state.doc.rounds.length)return;const [q]=state.doc.rounds.splice(state.index,1);state.doc.rounds.splice(target,0,q);state.index=target;markDirty();renderRound();}
$('move-up').onclick=()=>move(-1);$('move-down').onclick=()=>move(1);
$('duplicate-round').onclick=()=>{if(state.doc.rounds.length>=100)return;const q=structuredClone(round());q.id=roundId();state.doc.rounds.splice(state.index+1,0,q);state.index++;markDirty();renderRound();};
$('remove-round').onclick=()=>{if(!confirm('Убрать этот раунд из игры?'))return;state.doc.rounds.splice(state.index,1);state.index=Math.min(state.index,state.doc.rounds.length-1);markDirty();renderRound();};

async function save() {
  if(!state.dirty)return;
  const snapshot=await api('/games/'+id(),'PUT',{document:state.doc,revision:state.snapshot.revision});
  accept(snapshot,state.index);await refresh();
}
$('save').onclick=guarded(async()=>{await save();notice('Черновик сохранён. Опубликованная игра пока без изменений.');});
$('publish').onclick=guarded(async()=>{await save();const snapshot=await api('/games/'+id()+'/publish','POST',{revision:state.snapshot.revision});accept(snapshot,state.index);await refresh();notice('Игра опубликована. В Mini App нажми «Обновить список игр».');});
$('reload-published').onclick=guarded(async()=>{if(!confirm('Загрузить опубликованную версию? Текущий черновик будет заменён, его резервная копия сохранится.'))return;accept(await api('/games/'+id()+'/reload','POST'));await refresh();notice('Загружена опубликованная версия.');});
$('export').onclick=guarded(async()=>{await save();const response=await fetch('/api/games/'+id()+'/export');if(!response.ok){const result=await response.json();throw new Error(result.detail||'Не удалось скачать пакет.');}const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=state.snapshot.id+'.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);});
$('import-json').onchange=guarded(async()=>{const file=$('import-json').files[0];if(!file)return;try{if(file.size>1024*1024)throw new Error('Документ должен быть не больше 1 МБ.');const doc=JSON.parse(await file.text());if(!doc||typeof doc!=='object'||Array.isArray(doc)||!Array.isArray(doc.rounds)||doc.rounds.length>100||doc.rounds.some(q=>!q||typeof q!=='object'||!['question','event'].includes(q.type)))throw new Error('Нужен game.json со списком вопросов и событий.');if(!confirm('Заменить содержание игры из файла? Опубликованная версия не изменится до публикации.'))return;state.doc=doc;state.index=doc.rounds.length?0:-1;$('game-title').value=doc.title||'';$('game-description').value=doc.description||'';$('editor-title').textContent=doc.title||'Без названия';markDirty();renderRound();notice('Вопросы импортированы. При необходимости загрузи материалы к ним.');}finally{$('import-json').value='';}});

function newGameDialog() {if(!state.busy&&canLeave()){$('new-title').value='';$('create-dialog').showModal();$('new-title').focus();}}
$('new-game').onclick=newGameDialog;$('empty-create').onclick=newGameDialog;
$('cancel-create').onclick=()=>$('create-dialog').close();
$('create-form').onsubmit=guarded(async()=>{const title=$('new-title').value.trim();if(!title)throw new Error('Введите название игры.');const snapshot=await api('/games','POST',{title});$('create-dialog').close();accept(snapshot);await refresh();addRound('question');$('question-text').focus();});
$('game-list').onclick=guarded(async event=>{const button=event.target.closest('[data-game]');if(button)await openGame(button.dataset.game);});
$('refresh').onclick=guarded(refresh);$('search').oninput=renderLibrary;
async function entered() {show('login-panel',false);show('studio',true);show('account-actions',true);await refresh();}
$('login-form').onsubmit=guarded(async()=>{await api('/login','POST',{password:$('password').value});$('password').value='';await entered();});
$('logout').onclick=guarded(async()=>{if(!canLeave())return;await api('/logout','POST');state.snapshot=null;state.doc=null;state.index=-1;state.dirty=false;show('editor',false);show('empty',true);loginScreen();});
window.addEventListener('beforeunload',event=>{if(state.dirty||state.busy){event.preventDefault();event.returnValue='';}});
guarded(async()=>{try{await api('/me');await entered();}catch(error){loginScreen();if(error.message!=='Войдите в конструктор')notice(error.message,'error');}})();
