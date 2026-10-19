function countLabel(n,words) {const mod=n%100;return n+' '+words[mod>=11&&mod<=14?2:n%10===1?0:n%10>=2&&n%10<=4?1:2];}
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const show = (id, visible) => { $(id).hidden = !visible; };
const state = {games:[], snapshot:null, doc:null, index:-1, stageIndex:0, dirty:false, busy:false};
let deleteTarget=null, noticeTimer=null;
const modeTitles={blitz:'Блиц',grid:'Сетка вопросов',binary:'Выбор из двух'};
function normalizeStages(doc) {
  if(!Array.isArray(doc.stages))doc.stages=[{id:'legacy',type:'blitz',title:'Раунд 1',order:'sequential',chooser:'winner',auto_advance:false}];
  for(const q of doc.rounds||[])if(doc.stages.length)q.stage??=doc.stages[0].id;
  normalizeStageCategories(doc);
}
function stage() {return state.doc?.stages[state.stageIndex];}
function stageQuestions() {return state.doc?.rounds.map((q,i)=>({q,i})).filter(({q})=>q.stage===stage()?.id)||[];}
function isBinary(q=round()) {return q?.type==='question'&&(stage()?.type==='binary'||Array.isArray(q.choices));}
function binaryDefaults(q) {
  if(!Array.isArray(q.choices))q.choices=[q.answer?.slice(0,100)||'Да',q.answer?.toLowerCase()==='нет'?'Да':'Нет'];
  q.correct_choice??=0;q.answer=q.choices[q.correct_choice]||'';q.accepted_answers=[];
}

function notice(message='', type='info') {
  clearTimeout(noticeTimer);noticeTimer=null;
  $('notice-text').textContent=message; $('notice').dataset.type=type; show('notice',!!message);
  if(message&&type!=='error')noticeTimer=setTimeout(()=>notice(),6000);
}
$('dismiss-notice').onclick=()=>notice();
function loginScreen() {show('login-panel',true);show('studio',false);show('account-actions',false);}
async function api(path, method='GET', data) {
  const response=await fetch('/api'+path, {method,headers:{'X-Builder-Request':'1',...(data!==undefined?{'Content-Type':'application/json'}:{})},...(data!==undefined?{body:JSON.stringify(data)}:{})});
  const result=await response.json();
  if(!response.ok) {if(response.status===401)loginScreen();const error=new Error(typeof result.detail==='string'?result.detail:result.detail?.message||'Проверь заполненные поля.');error.issues=result.detail?.issues;throw error;}
  return result;
}
function guarded(fn) {
  return async event => {
    event?.preventDefault(); if(state.busy)return;
    state.busy=true;notice();updateActions();
    try {await fn(event);} catch(error) {if(error.issues)setPublicationIssues(error.issues,true);notice(error.message||'Не удалось связаться с сервером.','error');}
    finally {state.busy=false;updateActions();}
  };
}
function updateActions() {
  for(const id of ['save','publish','export','reload-published','new-game','add-question','add-event','refresh','logout','move-up','move-down','duplicate-round','remove-round','remove-media','add-stage','stage-up','stage-down','stage-delete'])$(id).disabled=state.busy;
  $('save').disabled=state.busy||!state.dirty;
  $('add-question').disabled=$('add-event').disabled=state.busy||!stage()||(state.doc?.rounds.length??0)>=100;
  $('add-event').disabled||=stage()?.type==='grid';
  const positions=stageQuestions().map(({i})=>i),position=positions.indexOf(state.index);
  $('move-up').disabled=state.busy||position<=0;
  $('move-down').disabled=state.busy||position<0||position>=positions.length-1;
  $('stage-up').disabled=state.busy||state.stageIndex<=0;
  $('stage-down').disabled=state.busy||state.stageIndex>=(state.doc?.stages.length??0)-1;
  $('stage-delete').disabled=state.busy||!stage();
  $('add-stage').disabled=state.busy||(state.doc?.stages.length??0)>=30;
  for(const id of ['duplicate-round','remove-round'])$(id).disabled=state.busy||state.index<0;
  for(const id of ['delete-current-game','confirm-delete-game','cancel-delete-game'])$(id).disabled=state.busy;
  for(const button of $('game-list').querySelectorAll('[data-delete-game]'))button.disabled=state.busy;
  $('media-file').disabled=state.busy;
  $('import-json').disabled=state.busy;
  // Freeze editable fields while saving so a delayed response cannot replace new typing.
  for(const input of $('editor').querySelectorAll('input:not([type=file]), textarea, select'))input.disabled=state.busy;
  updateCategoryActions();
  updateClipActions();
  renderGameSettings();
  renderEditorNavigation();
  const message=state.dirty?'Есть несохранённые изменения':state.snapshot?.dirty?'Черновик сохранён':'Опубликована';
  $('save-status').textContent=message;$('save-status').dataset.dirty=state.dirty;
  renderPublicationValidation();
}
function markDirty(refreshLists=true) {
  state.dirty=true;
  if(editorNav.search&&round()&&!visibleStageItems().some(({i})=>i===state.index)){
    editorNav.search='';$('question-search').value='';
  }
  if(refreshLists){updateActions();renderStages();renderRounds();renderCategoryOverview();}
  else {
    // Clip bounds do not change the library, categories or navigation.
    $('save').disabled=state.busy;$('save-status').textContent='Есть несохранённые изменения';$('save-status').dataset.dirty=true;
  }
  schedulePublicationValidation();
}
function canLeave() {return !state.dirty||confirm('В игре есть несохранённые изменения. Продолжить без сохранения?');}
function round() {return state.doc?.rounds[state.index];}
function id() {return encodeURIComponent(state.snapshot.id);}
function roundId() {return 'r-'+crypto.randomUUID().replaceAll('-','').slice(0,16);}

function renderLibrary() {
  const search=$('search').value.trim().toLowerCase();
  const filtered=state.games.filter(g=>(g.title+' '+g.description).toLowerCase().includes(search));
  $('game-list').innerHTML=filtered.length?filtered.map(g=>`<div class="game-library-item"><button class="game-card ${g.id===state.snapshot?.id?'active':''}" data-game="${esc(g.id)}"><strong>${esc(g.title)}</strong><small>${countLabel(g.questions,['вопрос','вопроса','вопросов'])} · ${countLabel(g.stages_count??1,['раунд','раунда','раундов'])}</small><span class="game-badge ${g.error?'error':''}">${g.error?'Ошибка пакета':g.dirty?'Есть черновик':g.published?'В библиотеке':'Новая игра'}</span></button><button class="icon-button game-delete danger-text" data-delete-game="${esc(g.id)}" aria-label="Удалить игру ${esc(g.title)}" title="Удалить игру" ${state.busy?'disabled':''}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 10v7m4-7v7"/></svg></button></div>`).join(''):`<p class="library-empty">${search?'Ничего не найдено.':'Пока нет игр. Начни с новой.'}</p>`;
}
async function refresh() {state.games=await api('/games');renderLibrary();}
function accept(snapshot, selected=0, selectedStage=null) {
  resetPublicationValidation();
  if(state.snapshot?.id!==snapshot.id)resetEditorNavigation();
  state.snapshot=snapshot;state.doc=structuredClone(snapshot.document);state.dirty=false;
  if(!Array.isArray(state.doc.rounds))state.doc.rounds=[];
  normalizeStages(state.doc);
  state.index=state.doc.rounds.length?Math.min(selected,state.doc.rounds.length-1):-1;
  state.stageIndex=Math.max(0,state.doc.stages.findIndex(s=>s.id===(selectedStage||state.doc.rounds[state.index]?.stage)));
  $('game-title').value=state.doc.title||'';$('game-description').value=state.doc.description||'';
  $('editor-title').textContent=state.doc.title||'Без названия';
  show('empty',false);show('editor',true);show('reload-published',snapshot.published);
  sessionStorage.setItem('builder-game',snapshot.id);setLibraryOpen(false);
  renderLibrary();renderStages();renderStageSettings();renderRounds();renderRound();updateActions();
}
async function openGame(gameId) {
  if(!canLeave())return;
  accept(await api('/games/'+encodeURIComponent(gameId)+'/open','POST'));
}
function renderRounds() {
  if(!state.doc)return;
  const questions=state.doc.rounds.filter(q=>q?.type==='question').length;
  const events=state.doc.rounds.filter(q=>q.type==='event').length;
  $('round-count').textContent=countLabel(questions,['вопрос','вопроса','вопросов'])+' · '+countLabel(events,['событие','события','событий'])+' · '+countLabel(state.doc.stages.length,['раунд','раунда','раундов']);
  renderCategoryOverview();
  const items=visibleStageItems();show('no-rounds',!items.length);
  $('round-list').innerHTML=items.map(({q,i},n)=>`<li><button class="${i===state.index?'selected':''}" data-round="${i}" aria-pressed="${i===state.index}"><span class="round-number">${String(n+1).padStart(2,'0')}</span><span class="round-name"><small>${q.type==='event'?'✳ СОБЫТИЕ':'ВОПРОС'}${q.media?' · МЕДИА':''}</small>${esc(q.type==='event'?q.title||'Новое событие':q.text||'Новый вопрос')}</span></button></li>`).join('');
}
function renderStages() {
  if(!state.doc)return;
  $('stage-count').textContent=state.doc.stages.length+' / 30';
  $('stage-list').innerHTML=state.doc.stages.map((s,i)=>`<li><button data-stage="${i}" class="${i===state.stageIndex?'selected':''}" aria-current="${i===state.stageIndex?'step':'false'}"><span>${String(i+1).padStart(2,'0')} · ${esc(modeTitles[s.type]||s.type)}</span><strong>${esc(s.title||'Без названия')}</strong><small>${countLabel(state.doc.rounds.filter(q=>q.stage===s.id&&q.type==='question').length,['вопрос','вопроса','вопросов'])}</small></button></li>`).join('');
}
function renderStageSettings() {
  const s=stage();if(!s)return;
  normalizeStageCategories(state.doc);
  $('stage-heading').textContent='Раунд '+(state.stageIndex+1);
  $('stage-title').value=s.title||'';$('stage-type').value=s.type;
  $('stage-order').value=s.order||'sequential';$('stage-auto').value=s.auto_advance?'auto':'manual';$('stage-chooser').value=s.chooser||'winner';$('stage-answer-mode').value=s.answer_mode||'all';
  $('stage-answer-penalties').value=s.answer_penalties===false?'off':'on';$('stage-trap-penalties').value=s.trap_penalties===false?'off':'on';
  show('stage-linear-settings',s.type!=='grid');show('stage-grid-settings',s.type==='grid');
  $('stage-explanation').textContent=s.type==='grid'?'Категории и стоимость вопросов образуют сетку. Первый вопрос выбирает ведущий; если никто не ответил верно, выбор возвращается ему. События добавляй в другие раунды.':s.type==='binary'?'У каждого вопроса две кнопки со своими подписями. Можно повторять этот режим и сочетать его с любыми другими раундами.':'Все отвечают на вопросы один за другим. Случайный порядок перемешивает вопросы, сохраняя позиции событий.';
  $('new-category').value='';renderCategoryControls();
}
function selectStage(index) {resetStageNavigation();editorNav.gameTab='rounds';state.stageIndex=index;state.index=stageQuestions()[0]?.i??-1;renderStages();renderStageSettings();renderRounds();renderRound();updateActions();}
$('stage-list').onclick=e=>{const button=e.target.closest('[data-stage]');if(button&&!state.busy)selectStage(Number(button.dataset.stage));};
$('add-stage').onclick=()=>{if(state.busy||state.doc.stages.length>=30)return;const type=$('new-stage-type').value;state.doc.stages.push({id:roundId(),type,title:'Раунд '+(state.doc.stages.length+1),order:'sequential',chooser:'winner',auto_advance:false});selectStage(state.doc.stages.length-1);addRound('question');};
for(const [field,key] of [['stage-title','title'],['stage-order','order'],['stage-chooser','chooser'],['stage-answer-mode','answer_mode'],['stage-auto','auto_advance']])$(field).oninput=()=>{if(!stage())return;stage()[key]=key==='auto_advance'?$(field).value==='auto':$(field).value;markDirty();};
for(const [field,key] of [['stage-answer-penalties','answer_penalties'],['stage-trap-penalties','trap_penalties']])$(field).oninput=()=>{if(!stage())return;stage()[key]=$(field).value==='on';markDirty();};
$('stage-type').onchange=()=>{const old=stage().type;stage().type=$('stage-type').value;normalizeStageCategories(state.doc);for(const {q} of stageQuestions()){if(q.type!=='question')continue;if(stage().type==='binary')binaryDefaults(q);else if(old==='binary'){delete q.choices;delete q.correct_choice;}}markDirty();renderStageSettings();renderRound();};
function moveStage(delta) {const target=state.stageIndex+delta;if(target<0||target>=state.doc.stages.length)return;const [s]=state.doc.stages.splice(state.stageIndex,1);state.doc.stages.splice(target,0,s);state.stageIndex=target;markDirty();renderStageSettings();}
$('stage-up').onclick=()=>moveStage(-1);$('stage-down').onclick=()=>moveStage(1);
$('stage-delete').onclick=()=>{
  const s=stage();if(state.busy||!s)return;
  const items=stageQuestions(),questions=items.filter(({q})=>q.type==='question').length,events=items.length-questions;
  const contents=countLabel(questions,['вопрос','вопроса','вопросов'])+(events?' и '+countLabel(events,['событие','события','событий']):'');
  if(!confirm(`Удалить раунд «${s.title||'Без названия'}»? Вместе с ним будут удалены ${contents}. Изменения вступят в силу после публикации.`))return;
  pauseClipEditor();state.doc.rounds=state.doc.rounds.filter(q=>q.stage!==s.id);
  state.doc.stages.splice(state.stageIndex,1);resetPublicationValidation();
  selectStage(Math.min(state.stageIndex,state.doc.stages.length-1));markDirty();
};
function renderRound() {
  const q=round();show('round-empty',!q);show('round-details',!!q);if(!q){renderClipEditor();disposeEditorMedia($('preview-media'));$('preview-content').replaceChildren();return;}
  const event=q.type==='event';show('question-fields',!event);show('event-fields',event);
  $('round-type').textContent=event?'СОБЫТИЕ':'ВОПРОС';$('round-heading').textContent=(event?'Событие ':'Вопрос ')+(stageQuestions().findIndex(({i})=>i===state.index)+1);
  if(event) {
    $('event-title').value=q.title||'';$('event-text').value=q.text||'';
    $('effect-type').value=q.effect?.type||'random_buff';$('effect-target').value=q.effect?.target||'random_player';$('effect-duration').value=q.effect?.questions??1;
    renderEffect();
  } else {
    const binary=isBinary(q);show('text-answer-fields',!binary);show('binary-answer-fields',binary);
    if(binary){$('choice-a').value=q.choices?.[0]??'Да';$('choice-b').value=q.choices?.[1]??'Нет';$('correct-choice').value=q.correct_choice??0;}
    $('question-text').value=q.text||'';$('answer').value=q.answer||'';
    $('accepted-answers').value=Array.isArray(q.accepted_answers)?q.accepted_answers.join('\n'):'';$('points').value=q.points??'';$('time-limit').value=q.time_limit??'';
    renderQuestionDefaults();
    $('answer-variants').open=Array.isArray(q.accepted_answers)&&q.accepted_answers.length>0;
    $('material-panel').open=!!q.media;
    $('media-type').value=q.media?.type||'';renderMediaFields();renderCategorySelect();
  }
  renderClipEditor();renderPreview();updateActions();
}
function renderMediaFields() {
  const m=round()?.media,type=m?.type||'';
  show('media-fields',!!type);show('clip-fields',type==='audio'||type==='video');show('attached-file',!!m?.file);
  show('media-display-option',!!type);$('media-show-in-question').checked=m?.show_in_question??!m?.audio_only;
  $('file-name').textContent=typeof m?.file==='string'?m.file.split('/').pop():'';
  $('media-file').value='';$('media-file').accept=type==='image'?'.png,.jpg,.jpeg,.jfif,.gif,.webp,.avif,.bmp':type==='audio'?'.mp3,.wav,.ogg,.oga,.opus,.m4a,.aac,.flac':'.mp4,.webm,.mov,.m4v';
  $('upload-label').textContent=m?.file?'Заменить материал':'Выбрать файл';
  $('material-status').textContent=m?.file?'файл добавлен':type?'выбери файл':'не добавлен';
  renderClipEditor();
}
function mediaURL(file) {return '/api/games/'+id()+'/media?file='+encodeURIComponent(file);}
function renderPreview() {
  const q=round();if(!q)return;
  const box=$('preview-content'),m=q.media;
  const key=q.type==='question'&&m?.file?JSON.stringify([state.snapshot.id,q.id,m.type,m.file,m.show_in_question??!m.audio_only]):'';
  const previous=$('preview-media');
  const reusable=!!key&&previous?.dataset.mediaKey===key;
  if(reusable)previous.remove();
  else disposeEditorMedia(previous);

  if(q.type==='event') {
    const targetTitles={all_players:'всем игрокам',random_player:'случайному игроку',leader:'лидеру',last_player:'последнему игроку'};
    box.innerHTML=`<div class="preview-meta"><span>СОБЫТИЕ · ${eventOption(q.effect)?.positive?'ПОЛОЖИТЕЛЬНОЕ':'ОТРИЦАТЕЛЬНОЕ'}</span><span>${esc(countLabel(q.effect?.questions??1,['вопрос','вопроса','вопросов']))}</span></div><h3>${esc(q.title||'Название события')}</h3><p>${esc(q.text||'Описание события появится здесь.')}</p><div class="preview-answer">${esc(eventOption(q.effect)?.title||'Эффект')} · ${esc(targetTitles[q.effect?.target]||'получатели не заданы')}<p>${esc(eventDescription(q.effect))}</p></div>`;
    return;
  }
  box.innerHTML=`<div class="preview-meta"><span>${esc(stage()?.type==='grid'?q.category||'Категория не выбрана':modeTitles[stage()?.type]||'ВОПРОС')}</span><span>${esc(questionValue(q,'points'))} очков · ${esc(questionValue(q,'time_limit'))} сек.</span></div><h3>${esc(q.text||'Текст вопроса появится здесь.')}</h3><div id="preview-media"></div><div class="preview-answer">Ответ для ведущего: <strong>${esc(q.choices?.[q.correct_choice]||q.answer||'Ещё не указан')}</strong></div>`;
  if(Array.isArray(q.choices)){const choices=document.createElement('div');choices.className='choice-preview';choices.innerHTML=q.choices.map(c=>`<span>${esc(c)}</span>`).join('');box.insertBefore(choices,box.querySelector('.preview-answer'));}
  if(reusable){$('preview-media').replaceWith(previous);return;}
  if(typeof m?.file!=='string'||!m.file||!['image','audio','video'].includes(m.type))return;
  const container=$('preview-media');container.dataset.mediaKey=key;
  const hiddenPicture=(m.show_in_question??!m.audio_only)===false;
  if(m.type==='image'&&hiddenPicture){container.textContent='Изображение появится на демонстрации вместе с ответом.';return;}
  const node=document.createElement(m.type==='image'?'img':m.type==='video'&&hiddenPicture?'audio':m.type);node.src=mediaURL(m.file);
  node.onerror=()=>{if($('preview-media')!==container)return;disposeEditorMedia(container);container.replaceChildren(Object.assign(document.createElement('p'),{textContent:'Материал не найден. Загрузи файл для этого вопроса.'}));};
  if(m.type==='image')node.alt='Материал к вопросу';
  else {
    node.controls=true;node.preload='metadata';if(m.type==='video')node.setAttribute('playsinline','');
    const bounds=()=>{const media=round()?.media;return {start:typeof media?.start==='number'&&Number.isFinite(media.start)?media.start:0,end:typeof media?.end==='number'&&Number.isFinite(media.end)?media.end:null};};
    node.addEventListener('loadedmetadata',()=>{if($('preview-media')!==container)return;const {start}=bounds();if(start<node.duration)node.currentTime=start;});
    node.addEventListener('play',()=>{if($('preview-media')!==container)return;const {start,end}=bounds();if(node.currentTime<start||(end!=null&&node.currentTime>=end))node.currentTime=start;});
    node.addEventListener('timeupdate',()=>{if($('preview-media')!==container)return;const {end}=bounds();if(!node.paused&&end!=null&&node.currentTime>=end)node.pause();});
  }
  $('preview-media').append(node);
}
function bind(field, getter, setter) {
  $(field).addEventListener('input',()=>{if(!round())return;setter(round(),getter($(field).value));markDirty();renderPreview();});
}
for(const [field,key] of [['question-text','text'],['answer','answer'],['event-title','title'],['event-text','text']])bind(field,v=>v,(q,v)=>q[key]=v);
for(const [field,key] of [['points','points'],['time-limit','time_limit']])bind(field,v=>v.trim()===''?null:Number(v),(q,v)=>{if(v===null)delete q[key];else q[key]=v;});
for(const [field,index] of [['choice-a',0],['choice-b',1]])bind(field,v=>v,(q,v)=>{binaryDefaults(q);q.choices[index]=v;q.answer=q.choices[q.correct_choice];});
bind('correct-choice',Number,(q,v)=>{binaryDefaults(q);q.correct_choice=v;q.answer=q.choices[v];});
bind('accepted-answers',v=>v.split('\n').map(s=>s.trim()).filter(Boolean),(q,v)=>q.accepted_answers=v);
for(const [field,key] of [['effect-target','target'],['effect-duration','questions']])bind(field,v=>field==='effect-duration'?Number(v):v,(q,v)=>{q.effect??={};q.effect[key]=v;renderEffect();});
$('media-type').onchange=()=>{if(!round())return;const type=$('media-type').value;if(type)round().media={type,file:'',start:0};else delete round().media;markDirty();renderMediaFields();renderPreview();};
$('media-show-in-question').onchange=()=>{const media=round()?.media;if(!media||state.busy)return;media.show_in_question=$('media-show-in-question').checked;delete media.audio_only;markDirty();renderPreview();};
$('remove-media').onclick=()=>{delete round().media;$('media-type').value='';markDirty();renderMediaFields();renderPreview();};
$('media-file').onchange=guarded(async()=>{
  const file=$('media-file').files[0];$('media-file').value='';if(!file)return;if(file.size>25*1024*1024)throw new Error('Файл должен быть не больше 25 МБ.');
  const q=round(),type=q.media.type;pauseClipEditor();
  const result=await uploadEditorMedia(file,type);
  q.media={...q.media,type:result.type,file:result.file};markDirty();renderMediaFields();renderPreview();notice('Материал загружен. Сохрани черновик, чтобы сохранить его в вопросе.');
});
for(const [field,key] of [['game-title','title'],['game-description','description']])$(field).oninput=()=>{state.doc[key]=$(field).value;$('editor-title').textContent=state.doc.title||'Без названия';markDirty();};

function addRound(type) {
  if(state.busy||!stage()||state.doc.rounds.length>=100)return;
  const q=type==='event'?{id:roundId(),type,title:'',text:'',effect:{type:'random_buff',target:'random_player',questions:1}}:{id:roundId(),type,text:'',answer:'',accepted_answers:[]};
  q.stage=stage().id;if(stage().type==='binary'&&type==='question')binaryDefaults(q);
  if(stage().type==='grid'&&editorNav.filter?.kind==='category')q.category=gridCategories().find(c=>categoryKey(c)===editorNav.filter.name);
  editorNav.search='';$('question-search').value='';editorNav.gameTab='rounds';editorNav.stageTab='questions';
  const insertion=state.index>=0?state.index+1:state.doc.rounds.length;
  state.doc.rounds.splice(insertion,0,q);state.index=insertion;markDirty();renderRound();
}
$('add-question').onclick=()=>addRound('question');$('add-event').onclick=()=>addRound('event');
$('round-list').onclick=event=>{const button=event.target.closest('[data-round]');if(!button||state.busy)return;state.index=Number(button.dataset.round);renderRounds();renderRound();};
function move(delta) {const positions=stageQuestions().map(({i})=>i),target=positions[positions.indexOf(state.index)+delta];if(target===undefined)return;[state.doc.rounds[state.index],state.doc.rounds[target]]=[state.doc.rounds[target],state.doc.rounds[state.index]];state.index=target;markDirty();renderRound();}
$('move-up').onclick=()=>move(-1);$('move-down').onclick=()=>move(1);
$('duplicate-round').onclick=()=>{if(state.doc.rounds.length>=100)return;const q=structuredClone(round());q.id=roundId();state.doc.rounds.splice(state.index+1,0,q);state.index++;markDirty();renderRound();};
$('remove-round').onclick=()=>{if(!confirm('Убрать этот вопрос или событие из игры?'))return;state.doc.rounds.splice(state.index,1);state.index=visibleStageItems().find(({i})=>i>=state.index)?.i??visibleStageItems().at(-1)?.i??-1;markDirty();renderRound();};

async function save() {
  if(!state.dirty)return;
  const snapshot=await api('/games/'+id(),'PUT',{document:state.doc,revision:state.snapshot.revision});
  accept(snapshot,state.index,stage()?.id);await refresh();
}
$('save').onclick=guarded(async()=>{await save();notice('Черновик сохранён. Опубликованная игра пока без изменений.');});
$('publish').onclick=guarded(async()=>{if(!await validatePublication(true))return;await save();const snapshot=await api('/games/'+id()+'/publish','POST',{revision:state.snapshot.revision});accept(snapshot,state.index,stage()?.id);await refresh();notice('Игра опубликована. В Mini App нажми «Обновить список игр».');});
$('publication-error-list').onclick=event=>{const button=event.target.closest('[data-publication-issue]');if(button&&!state.busy)openPublicationIssue(publicationValidation.issues[Number(button.dataset.publicationIssue)]);};
$('reload-published').onclick=guarded(async()=>{if(!confirm('Загрузить опубликованную версию? Текущий черновик будет заменён, его резервная копия сохранится.'))return;accept(await api('/games/'+id()+'/reload','POST'));await refresh();notice('Загружена опубликованная версия.');});
$('export').onclick=guarded(async()=>{if(!await validatePublication(true))return;await save();const response=await fetch('/api/games/'+id()+'/export');if(!response.ok){const result=await response.json();const error=new Error(typeof result.detail==='string'?result.detail:result.detail?.message||'Не удалось скачать пакет.');error.issues=result.detail?.issues;throw error;}const url=URL.createObjectURL(await response.blob()),link=document.createElement('a');link.href=url;link.download=state.snapshot.id+'.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);});
$('import-json').onchange=guarded(async()=>{const file=$('import-json').files[0];if(!file)return;try{if(file.size>1024*1024)throw new Error('Документ должен быть не больше 1 МБ.');const doc=JSON.parse(await file.text());if(!doc||typeof doc!=='object'||Array.isArray(doc)||!Array.isArray(doc.rounds)||doc.rounds.length>100||(doc.stages!==undefined&&(!Array.isArray(doc.stages)||doc.stages.length>30||doc.stages.some(s=>!s||typeof s.id!=='string'||!modeTitles[s.type])))||doc.rounds.some(q=>!q||typeof q!=='object'||!['question','event'].includes(q.type)))throw new Error('Нужен game.json со списком вопросов и событий.');if(!confirm('Заменить содержание игры из файла? Опубликованная версия не изменится до публикации.'))return;resetPublicationValidation();normalizeStages(doc);state.doc=doc;state.stageIndex=0;resetStageNavigation();editorNav.gameTab='rounds';state.index=stageQuestions()[0]?.i??-1;$('game-title').value=doc.title||'';$('game-description').value=doc.description||'';$('editor-title').textContent=doc.title||'Без названия';markDirty();renderStageSettings();renderRound();notice('Вопросы импортированы. При необходимости загрузи материалы к ним.');}finally{$('import-json').value='';}});

function newGameDialog() {if(!state.busy&&canLeave()){$('new-title').value='';$('create-dialog').showModal();$('new-title').focus();}}
$('new-game').onclick=newGameDialog;$('empty-create').onclick=newGameDialog;
$('cancel-create').onclick=()=>$('create-dialog').close();
$('create-form').onsubmit=guarded(async()=>{const title=$('new-title').value.trim();if(!title)throw new Error('Введите название игры.');const snapshot=await api('/games','POST',{title});$('create-dialog').close();accept(snapshot);await refresh();addRound('question');$('question-text').focus();});
function openDeleteDialog(gameId) {
  if(state.busy)return;
  const game=state.games.find(g=>g.id===gameId);if(!game)return;
  const current=state.snapshot?.id===gameId;
  deleteTarget={id:gameId,revision:game.delete_revision};
  $('delete-game-title').textContent=game.title;
  show('delete-game-error',false);
  $('delete-game-description').textContent=game.published?'Игра исчезнет из редактора и списка игр Telegram. Её черновик и медиафайлы будут удалены. Начатые комнаты продолжат работать.':'Черновик игры будет удалён вместе со всеми загруженными медиафайлами.';
  show('delete-unsaved-note',current&&state.dirty);
  $('delete-game-dialog').showModal();$('cancel-delete-game').focus();
}
$('delete-current-game').onclick=()=>openDeleteDialog(state.snapshot?.id);
$('cancel-delete-game').onclick=()=>{$('delete-game-dialog').close();deleteTarget=null;};
$('delete-game-dialog').oncancel=event=>{if(state.busy)event.preventDefault();else deleteTarget=null;};
$('delete-game-form').onsubmit=guarded(async()=>{
  if(!deleteTarget)return;
  const target=deleteTarget;
  try {await api('/games/'+encodeURIComponent(target.id),'DELETE',{revision:target.revision});}
  catch(error){$('delete-game-error').textContent=error.message;show('delete-game-error',true);throw error;}
  if(state.snapshot?.id===target.id){
    state.snapshot=null;state.doc=null;state.index=-1;state.stageIndex=0;state.dirty=false;
    sessionStorage.removeItem('builder-game');resetEditorNavigation();show('editor',false);show('empty',true);
  }
  $('delete-game-dialog').close();deleteTarget=null;await refresh();
  notice('Игра удалена вместе с черновиком и медиа. В Mini App обнови список игр.');
});
const openLibraryGame=guarded(async event=>{const button=event.target.closest('[data-game]');if(button)await openGame(button.dataset.game);});
$('game-list').onclick=event=>{const remove=event.target.closest('[data-delete-game]');if(remove)openDeleteDialog(remove.dataset.deleteGame);else openLibraryGame(event);};
$('refresh').onclick=guarded(refresh);$('search').oninput=renderLibrary;
async function entered() {show('login-panel',false);show('studio',true);show('account-actions',true);await refresh();const last=sessionStorage.getItem('builder-game');if(!state.doc&&state.games.some(g=>g.id===last))await openGame(last);}
$('login-form').onsubmit=guarded(async()=>{await api('/login','POST',{password:$('password').value});$('password').value='';await entered();});
$('logout').onclick=guarded(async()=>{if(!canLeave())return;await api('/logout','POST');pauseClipEditor();setLibraryOpen(false);sessionStorage.removeItem('builder-game');state.snapshot=null;state.doc=null;state.index=-1;state.dirty=false;show('editor',false);show('empty',true);loginScreen();});
initCategories();
initGameSettings();
initEditorNavigation();
initEvents();
initMediaEditor();
window.addEventListener('beforeunload',event=>{if(state.dirty||state.busy){event.preventDefault();event.returnValue='';}});
guarded(async()=>{try{await api('/me');await entered();}catch(error){loginScreen();if(error.message!=='Войдите в конструктор')notice(error.message,'error');}})();
