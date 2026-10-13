function countLabel(n,words) {const mod=n%100;return n+' '+words[mod>=11&&mod<=14?2:n%10===1?0:n%10>=2&&n%10<=4?1:2];}
const $ = id => document.getElementById(id);
const tg = window.Telegram?.WebApp;
const show = (id, visible) => $(id).hidden = !visible;
const notice = (text, type='info') => { $('notice').textContent = text || ''; $('notice').dataset.type = type; };
const esc = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let auth, config, room, socket, retry, offset = 0, mediaKey = '', uploading = false, libraryPacks = [];
const modeTitles={blitz:'Блиц',grid:'Сетка вопросов',binary:'Выбор из двух'};

function renderModes() {
  const stage=room.stage;
  show('stage-banner',!!stage&&!['lobby','finished'].includes(room.phase));
  if(stage){$('stage-mode').textContent=`Раунд ${room.stage_number} / ${room.stage_count} · ${modeTitles[stage.type]}`;$('stage-name').textContent=stage.title;$('stage-hint').textContent=stage.type==='grid'?'Выбираем тему и стоимость, затем все отвечают.':stage.type==='binary'?'Два варианта. Одна попытка. Проверка автоматически.':stage.order==='random'?'Вопросы в случайном порядке.':'Вопросы идут один за другим.';}
  show('question-board',stage?.type==='grid'&&['board','reveal'].includes(room.phase)&&!room.stage_complete);
  const chooser=room.players.find(p=>p.id===room.chooser);
  $('board-chooser').textContent=room.can_pick?'Выбери следующий вопрос.':`Выбирает ${chooser?.name||'ведущий'}.`;
  const categories=[...new Set((room.board||[]).map(q=>q.category))];
  $('board-cells').innerHTML=categories.map(c=>`<div class="board-row"><div class="board-category">${esc(c)}</div><div class="board-values">${room.board.filter(q=>q.category===c).sort((a,b)=>a.value-b.value).map(q=>`<button data-pick="${esc(q.id)}" ${!room.can_pick||q.used?'disabled':''} class="${q.used?'played':''}" aria-label="${esc(c)}: ${q.value} очков${q.used?', сыгран':''}">${q.used?'—':q.value}</button>`).join('')}</div></div>`).join('');
  const q=room.question,binary=Array.isArray(q?.choices);
  show('binary-options',binary&&room.phase!=='finished');
  $('binary-options').innerHTML=binary?q.choices.map((choice,i)=>`<button data-choice="${i}" ${canAnswer()?'':'disabled'} class="${ownAnswer()?.choice===i?'chosen':''} ${q.correct_choice===i?'correct-option':''} ${ownAnswer()?.choice===i&&ownAnswer()?.verdict==='wrong'?'wrong-option':''}">${esc(choice)}</button>`).join(''):'';
  show('auto-next',!!room.advance_at&&room.phase==='reveal');
}

async function api(path, body) {
  const response = await fetch('/api'+path, {method:body===undefined?'GET':'POST', headers:{'Content-Type':'application/json', ...(auth?{Authorization:'Bearer '+auth.token}:{})}, ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Проверьте введённые данные');
  return data;
}
function guard(fn) { let pending=false; return async event => {event?.preventDefault();if(pending)return;pending=true;notice('');try {await fn(event);} catch(e) {notice(e.message||'Нет связи с сервером','error');} finally {pending=false;}}; }
function ownAnswer() {return room?.answers?.[auth.user.id];}
function isHost() {return room?.host===auth.user.id;}
function hasControls() {return isHost() || (room?.practice && room.owner===auth.user.id);}
function canAnswer() {return room?.phase==='question' && !isHost() && !ownAnswer();}
function effectBadge(s, uid) {
  const active=(['question','review','reveal'].includes(s.phase)?s.round_modifiers:s.modifiers)?.[uid];
  if(!active)return '';
  const titles={double_reward:'Двойная награда',shield:'Защита от штрафа',half_reward:'Половина награды',double_penalty:'Двойной штраф'};
  return `<small class="effect-badge">${titles[active.kind]}</small>`;
}

function renderMedia(q) {
  const m=q?.media;
  const key=room.code+':'+q?.id+':'+JSON.stringify(m);
  if(key===mediaKey)return;
  mediaKey=key;$('media-content').replaceChildren();$('media-caption').textContent='';
  if(!m)return;
  const node=document.createElement(m.kind==='image'?'img':m.kind);
  node.src=m.url;
  node.onerror=()=>notice('Не удалось открыть материал. Проверьте формат файла или обновите игру.','error');
  if(m.kind==='image')node.alt='Материал к вопросу';
  else {
    node.controls=true;node.preload='metadata';
    if(m.kind==='video')node.setAttribute('playsinline','');
    const start=m.start||0,end=m.end;
    if(start||end!=null){
      $('media-caption').textContent=`Отрывок: ${start}–${end??'конец'} сек.`;
      node.addEventListener('loadedmetadata',()=>{if(start>=node.duration){notice('Начало отрывка за пределами записи.','error');return;}node.currentTime=start;});
      node.addEventListener('play',()=>{if(node.currentTime<start || (end!=null&&node.currentTime>=end-.05))node.currentTime=start;});
      node.addEventListener('timeupdate',()=>{if(end!=null&&node.currentTime>=end){node.pause();if(node.currentTime>end)node.currentTime=end;}});
      node.addEventListener('seeking',()=>{if(node.currentTime<start)node.currentTime=start;else if(end!=null&&node.currentTime>end)node.currentTime=end;});
    }
  }
  $('media-content').append(node);
}

function renderReview() {
  const visible=['review','reveal','finished'].includes(room.phase);
  $('review-list').innerHTML=visible?'<h3 class="review-heading">Ответы игроков</h3>'+room.players.filter(p=>p.id!==room.host).map(p=>{
    const a=room.answers[p.id];
    const status=!a?'Не ответил · 0 очков':a.verdict==='correct'?`Верно · ${a.points>=0?'+':''}${a.points}`:a.verdict==='wrong'?`Неверно · ${a.points}`:'Ожидает оценки';
    const buttons=isHost()&&room.phase==='review'&&a&&!a.verdict?`<div class="inline"><button data-player="${esc(p.id)}" data-verdict="correct">✓ Верно</button><button class="danger" data-player="${esc(p.id)}" data-verdict="wrong">✕ Неверно</button></div>`:'';
    return `<div class="review-answer" data-verdict="${a?.verdict||'pending'}"><strong>${esc(p.name)}</strong><p>${a?esc(a.text):'—'}</p><small>${status}</small>${buttons}</div>`;
  }).join(''):'';
}

function renderPlayers(s) {
  const sorted=[...s.players].sort((a,b)=>(a.id===s.host)-(b.id===s.host)||b.score-a.score);
  $('player-count').textContent=(s.players.length-1)+' / 8';
  $('players').innerHTML=sorted.map((p,i)=>{
    const host=p.id===s.host;
    const state=host?'Ведущий':s.phase==='question'&&s.answered_ids.includes(p.id)?'Ответ отправлен ✓':p.id===auth.user.id?'Это ты':p.synthetic?'Соперник':'В забеге';
    const color=[...p.id].reduce((n,c)=>n+c.charCodeAt(0),0)%4;
    return `<div class="player ${p.id===auth.user.id?'me':''} ${host?'host':''}" data-color="${color}"><span class="player-rank">${host?'—':String(i+1).padStart(2,'0')}</span><span class="player-avatar" aria-hidden="true">${esc([...p.name.trim()][0]?.toUpperCase()||'?')}</span><div class="player-info"><span class="player-name" title="${esc(p.name)}">${esc(p.name)}</span><em>${state}</em>${host?'':effectBadge(s,p.id)}</div><strong class="player-score">${host?'↗':p.score}</strong></div>`;
  }).join('');
}

function renderHostAnswers() {
  const visible=isHost()&&room.phase==='question';
  show('host-hint',visible);show('host-answers',visible);
  $('host-answers').innerHTML=visible?room.players.filter(p=>room.answers[p.id]).map(p=>`<div class="host-answer"><strong>${esc(p.name)}</strong><span>${esc(room.answers[p.id].text)}</span></div>`).join(''):'';
}

function renderPackPreview() {
  const id=$('pack').value;
  const pack=id==='demo'?libraryPacks.find(p=>p.id==='library-demo-quiz'):id==='custom'?{title:'Твой собственный квиз',description:'Начни с пустой комнаты. Добавь вопросы и материалы перед стартом игры.',questions:0,count:0}:libraryPacks.find(p=>p.id===id);
  if(!pack)return;
  $('pack-title').textContent=pack.title;
  $('pack-description').textContent=pack.description||'Готовая игра для тебя и твоей компании.';
  const tags=id==='custom'?['Вопросы в лобби']:[countLabel(pack.questions,['вопрос','вопроса','вопросов']),countLabel(pack.stages?.length||1,['раунд','раунда','раундов']),...[...new Set((pack.stages||[]).map(s=>modeTitles[s.type]))]];
  $('pack-tags').innerHTML=tags.map(t=>`<span>${esc(t)}</span>`).join('');
  $('practice').disabled=id==='custom';
  $('practice-caption').textContent=id==='custom'?'Для тренировки выбери готовую игру.':'Тренировка на выбранной игре.';
}

function renderChat(){
  const messages=room.messages||[],key=room.code+':'+(messages[messages.length-1]?.id||0)+':'+room.phase;
  const box=$('messages');
  if(box.dataset.key!==key){
    const bottom=box.scrollHeight-box.scrollTop-box.clientHeight<70;
    const first=!box.dataset.key?.startsWith(room.code+':');
    box.innerHTML=messages.length?messages.map(m=>`<div class="chat-message ${m.kind==='system'?'system':''} ${m.user_id===auth.user.id?'mine':''}"><strong>${esc(m.name)}${m.kind==='answer'?' · ответ':''}</strong><p>${esc(m.text)}</p></div>`).join(''):'<div class="chat-empty">Здесь будет обсуждение.<br>Начни с приветствия.</div>';
    box.dataset.key=key;if(bottom||first)box.scrollTop=box.scrollHeight;
  }
  const blocked=room.phase==='question';
  $('chat-hint').textContent=blocked?'Пока тихо: чат откроется после вопроса. Отправь ответ через поле в карточке вопроса.':'Обсуждай вопросы, радуйся очкам. Только без подсказок!';
  $('chat').dataset.blocked=blocked;
  $('chat-text').disabled=blocked;$('chat-send').disabled=blocked;
}

function apply(s){
  if(room&&s.code===room.code&&s.version<room.version)return;
  const oldQuestion=room?.code+':'+room?.active;
  room=s;offset=s.server_time*1000-Date.now();sessionStorage.setItem('room',s.code);
  $('game').dataset.phase=s.phase;
  show('home',false);show('game',true);
  $('room-code').textContent=s.code;
  $('phase').textContent=(s.practice?'Тренировка · ':'')+({board:'Выбираем вопрос',event:'Событие',lobby:'Ожидание игроков',question:s.question?.choices?'Выбираем вариант':'Все пишут ответы',review:'Ведущий проверяет ответы',reveal:'Результаты вопроса',ready:'Готовы продолжить',finished:'Квиз завершён'}[s.phase]||'');
  renderPlayers(s);
  show('round-status',s.phase!=='lobby');
  $('round-label').textContent=`Раунд ${s.stage_number} / ${s.stage_count} · Вопрос ${s.question_number} / ${s.question_count}`;
  $('round-progress').max=Math.max(1,s.round_count);$('round-progress').value=s.used.length;
  show('invite',!s.practice);show('lobby',s.phase==='lobby');show('start',isHost());$('start').disabled=uploading||s.players.length<2||!s.question_count;
  $('pack-count').textContent=`В игре ${s.question_count} вопросов, ${s.stage_count} игровых раундов: ${s.stages.map(stage=>modeTitles[stage.type]).join(' → ')}.`;show('waiting',!isHost());show('editor',isHost()&&s.phase==='lobby');
  if(s.phase==='lobby'){const selected=$('q-stage').value;$('q-stage').innerHTML=s.stages.map(stage=>`<option value="${esc(stage.id)}">${esc(stage.title)} · ${modeTitles[stage.type]}</option>`).join('');if(s.stages.some(stage=>stage.id===selected))$('q-stage').value=selected;renderQuestionEditor();}
  show('question-list-panel',isHost()&&s.phase==='lobby'&&!!s.question_count);
  $('question-list').innerHTML=(s.question_list||[]).map((q,i)=>`<p><span class="question-list-number">${String(i+1).padStart(2,'0')}</span><span class="question-list-text">${esc(q.type==='event'?'✳ '+q.title:q.text)}${q.media?' · '+({image:'Изображение',video:'Видео',audio:'Аудио'}[q.media.kind]):''}</span></p>`).join('');
  show('event',s.phase==='event');
  if(s.phase==='event'){const e=s.event;$('event-title').textContent=e.event_title;$('event-text').textContent=e.text;$('effect-title').textContent=e.title;$('effect-description').textContent=e.description;$('effect-targets').textContent='Получатели: '+e.targets.join(', ')+' · действует '+e.questions+' вопросов';show('event-next',hasControls());}
  const q=s.question;
  if(!q||s.phase==='finished')renderMedia(null);show('question',!!q&&s.phase!=='finished');
  if(q){
    $('category').textContent=`Вопрос ${s.question_number}/${s.question_count} · ${q.category}`;$('value').textContent=q.value+' очков';$('question-text').textContent=q.text;
    $('answer-count').textContent=`Ответили ${s.answered_ids.length} из ${s.players.length-1}`;
    show('answer-form',canAnswer()&&!q.choices);show('my-answer',!isHost()&&!!ownAnswer()&&s.phase==='question');
    $('my-answer').textContent=ownAnswer()?'Твой ответ: '+ownAnswer().text+' · отправлен':'';
    show('solution',!!q.answer);$('solution').textContent=q.answer?'Правильный ответ: '+q.answer:'';
    show('close',hasControls()&&s.phase==='question');show('next',hasControls()&&s.phase==='reveal');
    $('next').textContent=s.round_number===s.round_count?'Показать итоги →':s.stage_complete?'Следующий раунд →':s.stage?.type==='grid'?'Вернуться к сетке →':'Следующий вопрос →';
    if(oldQuestion!==s.code+':'+s.active){$('answer-text').value='';}
    if(s.phase!=='finished')renderMedia(q);renderReview();
  }
  renderHostAnswers();renderModes();
  show('ready',s.phase==='ready'&&hasControls());show('finished',s.phase==='finished');show('finish',hasControls()&&['reveal','event','board'].includes(s.phase));
  $('another').textContent=s.practice?'Ещё одна тренировка':'Новая комната';
  if(s.phase==='finished'){
    const players=s.players.filter(p=>p.id!==s.host).sort((a,b)=>b.score-a.score),top=Math.max(...players.map(p=>p.score));
    $('winner').textContent=players.filter(p=>p.score===top).map(p=>p.name).join(', ')+' — '+top+' очков';
    $('final-results').innerHTML=players.map(p=>`<div class="final-result"><span>${players.findIndex(other=>other.score===p.score)+1}</span><span class="result-name">${esc(p.name)}${p.id===auth.user.id?' · ты':''}</span><strong>${p.score} очков</strong></div>`).join('');
  }
  renderChat();tick();
}
function tick(){
  if(!room)return;
  const left=room.deadline?Math.max(0,room.deadline*1000-Date.now()-offset):null;
  const n=left===null?null:Math.ceil(left/1000),urgent=n!==null&&n<=10;
  $('timer').textContent=n===null?'':n===0?'Время вышло':`${n} сек.`;
  $('timer').dataset.urgent=urgent;$('timer-track').dataset.urgent=urgent;
  show('timer-track',n!==null);
  $('timer-bar').style.width=(left===null?0:Math.min(100,left/(room.question?.seconds||45)/10))+'%';
  $('answer-send').disabled=n===0;
  for(const button of $('binary-options').querySelectorAll('button'))button.disabled=!canAnswer()||n===0;
  if(room.advance_at)$('auto-next').textContent=`Следующий вопрос через ${Math.max(0,Math.ceil((room.advance_at*1000-Date.now()-offset)/1000))} сек.`;
}
setInterval(tick,250);
function connect(code){
  clearTimeout(retry);if(socket){socket.onclose=null;socket.close();}
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${code}`);socket=ws;
  ws.onopen=()=>{ws.send(JSON.stringify({token:auth.token}));$('connection').textContent='● На связи';$('connection').dataset.status='online';};
  ws.onmessage=e=>{if(socket!==ws)return;try{apply(JSON.parse(e.data));}catch{notice('Не удалось обновить игру','error');}};
  ws.onerror=()=>{$('connection').textContent='Нет связи';$('connection').dataset.status='offline';};
  ws.onclose=e=>{if(socket!==ws)return;$('connection').textContent='Переподключение…';$('connection').dataset.status='offline';if(e.code===1008){notice('Сессия истекла. Перезагрузите приложение.','error');return;}retry=setTimeout(()=>connect(code),1500);};
}
async function join(code){const s=await api('/rooms/'+encodeURIComponent(code.trim().toUpperCase())+'/join',{});apply(s);connect(s.code);}
async function create(){const s=await api('/rooms',{pack:$('pack').value});await join(s.code);}
async function practice(){const s=await api('/practice',{pack:$('pack').value});apply(s);connect(s.code);}
async function command(action,extra={}){apply(await api('/rooms/'+room.code+'/action',{action,...extra}));}
async function refreshPacks(){
  const data=await api('/packs'),selected=$('pack').value;libraryPacks=data.packs;
  $('pack').querySelectorAll('[data-library],[value=demo]').forEach(n=>n.remove());
  for(const p of data.packs){
    const o=document.createElement('option');o.value=p.id==='library-demo-quiz'?'demo':p.id;o.dataset.library='1';o.textContent=p.title+' · '+p.questions+' вопросов';
    if(o.value==='demo')$('pack').insertBefore(o,$('pack').firstChild);else $('pack').append(o);
  }
  if([...$('pack').options].some(o=>o.value===selected))$('pack').value=selected;
  $('pack-errors').textContent=data.errors.map(e=>e.folder+': '+e.error).join('; ');renderPackPreview();
}
$('pack').onchange=renderPackPreview;
$('reload-packs').onclick=guard(refreshPacks);$('event-next').onclick=guard(()=>command('next'));
async function entered(){await refreshPacks();sessionStorage.setItem('auth',JSON.stringify(auth));$('identity').textContent=auth.user.name;show('login',false);show('home',true);const p=new URLSearchParams(location.search),code=tg?.initDataUnsafe?.start_param||p.get('tgWebAppStartParam')||p.get('room')||sessionStorage.getItem('room');if(code&&/^[A-Z2-9]{6}$/i.test(code)){try{await join(code);}catch(e){notice(e.message);sessionStorage.removeItem('room');}}}
$('login-form').onsubmit=guard(async()=>{auth=await api('/login',{name:$('name').value});await entered();});
$('join-form').onsubmit=guard(()=>join($('code').value));$('create').onclick=guard(create);$('practice').onclick=guard(practice);$('another').onclick=guard(()=>room?.practice?practice():create());
for(const a of ['start','close','next'])$(a).onclick=guard(()=>command(a));$('resume').onclick=guard(()=>command('next'));
$('answer-form').onsubmit=guard(()=>command('answer',{text:$('answer-text').value}));
$('binary-options').onclick=guard(async event=>{const b=event.target.closest('[data-choice]');if(b&&!b.disabled)await command('answer',{choice:Number(b.dataset.choice)});});
$('board-cells').onclick=guard(async event=>{const b=event.target.closest('[data-pick]');if(b&&!b.disabled)await command('pick',{question:b.dataset.pick});});
const pendingGrades=new Set();
$('review-list').onclick=async e=>{
  const b=e.target.closest('button[data-verdict]');if(!b||pendingGrades.has(b.dataset.player))return;
  const player=b.dataset.player;pendingGrades.add(player);notice('');
  for(const button of $('review-list').querySelectorAll('button'))if(button.dataset.player===player)button.disabled=true;
  try{await command(b.dataset.verdict,{player});}catch(error){notice(error.message||'Нет связи с сервером','error');}
  finally{pendingGrades.delete(player);renderReview();}
};
$('chat-form').onsubmit=guard(async()=>{const text=$('chat-text').value;await command('message',{text});if($('chat-text').value===text)$('chat-text').value='';});
$('finish').onclick=guard(async()=>{if(confirm('Завершить квиз и показать итоговый счёт?'))await command('finish');});
$('leave').onclick=()=>{clearTimeout(retry);if(socket){socket.onclose=null;socket.close();socket=null;}sessionStorage.removeItem('room');room=null;$('media-content').replaceChildren();mediaKey='';show('game',false);show('home',true);notice('');history.replaceState(null,'',location.pathname);};
$('q-kind').onchange=()=>{const kind=$('q-kind').value;show('file-fields',!!kind);show('clip-fields',kind==='audio'||kind==='video');$('q-file').accept=kind==='image'?'.png,.jpg,.jpeg,.gif,.webp':kind==='audio'?'.mp3,.wav,.ogg,.m4a':'.mp4,.webm';$('q-file').required=!!kind;};
function renderQuestionEditor() {
  const selected=room?.stages.find(s=>s.id===$('q-stage').value),binary=selected?.type==='binary',grid=selected?.type==='grid';
  show('q-binary-fields',binary);$('q-answer').required=!binary;$('q-answer').hidden=binary;$('q-answer').previousElementSibling.hidden=binary;for(const id of ['q-choice-a','q-choice-b'])$(id).required=binary;
  show('q-category-field',grid);$('q-category').required=grid;
  const category=$('q-category').value;
  $('q-category').innerHTML='<option value="">Выбери категорию</option>'+(selected?.categories||[]).map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  if(selected?.categories?.includes(category))$('q-category').value=category;
}
$('q-stage').onchange=renderQuestionEditor;
$('question-form').onsubmit=guard(async()=>{
  if(uploading)return;
  const body={stage:$('q-stage').value,text:$('q-text').value,answer:$('q-answer').value,value:Number($('q-value').value),seconds:Number($('q-seconds').value),clip_start:Number($('clip-start').value||0),clip_end:$('clip-end').value?Number($('clip-end').value):null};
  if(room.stages.find(s=>s.id===body.stage)?.type==='grid')body.category=$('q-category').value;
  if(room.stages.find(s=>s.id===body.stage)?.type==='binary'){body.choices=[$('q-choice-a').value,$('q-choice-b').value];body.correct_choice=Number($('q-correct-choice').value);body.answer=body.choices[body.correct_choice];}
  const kind=$('q-kind').value,file=$('q-file').files[0];
  if(kind&&(!file||file.size>25*1024*1024))throw new Error('Выберите файл размером до 25 МБ');
  if(body.clip_end!=null&&body.clip_end<=body.clip_start)throw new Error('Конец отрывка должен быть позже начала');
  uploading=true;$('add-question').disabled=true;$('start').disabled=true;
  try{
    if(kind){const r=await fetch(`/api/rooms/${room.code}/media?kind=${kind}`,{method:'POST',headers:{Authorization:'Bearer '+auth.token,'Content-Type':file.type||'application/octet-stream'},body:file});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Не удалось загрузить файл');body.media_id=data.id;}
    apply(await api('/rooms/'+room.code+'/questions',body));$('question-form').reset();$('q-kind').onchange();renderQuestionEditor();notice('Вопрос добавлен в конец пакета.');
  }finally{uploading=false;$('add-question').disabled=false;if(room)$('start').disabled=room.players.length<2||!room.question_count;}
});
$('invite').onclick=guard(async()=>{const link=config.bot_username?`https://t.me/${config.bot_username}?start=${room.code}`:`${location.origin}/?room=${room.code}`;if(tg?.initData&&config.bot_username)tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent('Крысиные бега! Код: '+room.code)}`);else if(navigator.clipboard){await navigator.clipboard.writeText(link);notice('Ссылка скопирована. Код: '+room.code);}else notice('Код комнаты: '+room.code);});
window.addEventListener('online',()=>{if(room)connect(room.code);});document.addEventListener('visibilitychange',()=>{if(!document.hidden&&room)connect(room.code);});
function telegramEntry(){
  show('telegram-entry',true);
  if(config.bot_username){$('open-bot').href='https://t.me/'+encodeURIComponent(config.bot_username);show('open-bot',true);}
}
guard(async()=>{
  tg?.ready();tg?.expand();config=await api('/config');
  try{auth=JSON.parse(sessionStorage.getItem('auth'));}catch{auth=null;}
  if(auth){try{auth.user=await api('/me');}catch{auth=null;sessionStorage.removeItem('auth');}}
  if(!auth&&tg?.initData){try{auth=await api('/login',{init_data:tg.initData});}catch(e){telegramEntry();throw e;}}
  if(auth)await entered();else if(config.dev_mode)show('login',true);else telegramEntry();
})();
