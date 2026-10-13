const $ = id => document.getElementById(id);
const tg = window.Telegram?.WebApp;
const show = (id, visible) => $(id).hidden = !visible;
const notice = text => $('notice').textContent = text || '';
const esc = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let auth, config, room, socket, retry, offset = 0, mediaKey = '', uploading = false;

async function api(path, body) {
  const response = await fetch('/api'+path, {method:body===undefined?'GET':'POST', headers:{'Content-Type':'application/json', ...(auth?{Authorization:'Bearer '+auth.token}:{})}, ...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Проверьте введённые данные');
  return data;
}
function guard(fn) { return async event => {event?.preventDefault();notice('');try {await fn(event);} catch(e) {notice(e.message||'Нет связи с сервером');}}; }
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
  node.onerror=()=>notice('Не удалось открыть материал. Проверьте формат файла или обновите игру.');
  if(m.kind==='image')node.alt='Материал к вопросу';
  else {
    node.controls=true;node.preload='metadata';
    if(m.kind==='video')node.setAttribute('playsinline','');
    const start=m.start||0,end=m.end;
    if(start||end!=null){
      $('media-caption').textContent=`Отрывок: ${start}–${end??'конец'} сек.`;
      node.addEventListener('loadedmetadata',()=>{if(start>=node.duration){notice('Начало отрывка за пределами записи.');return;}node.currentTime=start;});
      node.addEventListener('play',()=>{if(node.currentTime<start || (end!=null&&node.currentTime>=end-.05))node.currentTime=start;});
      node.addEventListener('timeupdate',()=>{if(end!=null&&node.currentTime>=end){node.pause();if(node.currentTime>end)node.currentTime=end;}});
      node.addEventListener('seeking',()=>{if(node.currentTime<start)node.currentTime=start;else if(end!=null&&node.currentTime>end)node.currentTime=end;});
    }
  }
  $('media-content').append(node);
}

function renderReview() {
  const visible=['review','reveal','finished'].includes(room.phase);
  $('review-list').innerHTML=visible?room.players.filter(p=>p.id!==room.host).map(p=>{
    const a=room.answers[p.id];
    const status=!a?'Не ответил · 0 очков':a.verdict==='correct'?`Верно · ${a.points>=0?'+':''}${a.points}`:a.verdict==='wrong'?`Неверно · ${a.points}`:'Ожидает оценки';
    const buttons=isHost()&&room.phase==='review'&&a&&!a.verdict?`<div class="inline"><button data-player="${esc(p.id)}" data-verdict="correct">✓ Верно</button><button class="danger" data-player="${esc(p.id)}" data-verdict="wrong">✕ Неверно</button></div>`:'';
    return `<div class="review-answer"><strong>${esc(p.name)}</strong><p>${a?esc(a.text):'—'}</p><small>${status}</small>${buttons}</div>`;
  }).join(''):'';
}

function renderChat(){
  const messages=room.messages||[],key=room.code+':'+(messages[messages.length-1]?.id||0)+':'+room.phase;
  const box=$('messages');
  if(box.dataset.key!==key){
    const bottom=box.scrollHeight-box.scrollTop-box.clientHeight<70;
    const first=!box.dataset.key?.startsWith(room.code+':');
    box.innerHTML=messages.map(m=>`<div class="chat-message ${m.kind==='system'?'system':''} ${m.user_id===auth.user.id?'mine':''}"><strong>${esc(m.name)}${m.kind==='answer'?' · ответ':''}</strong><p>${esc(m.text)}</p></div>`).join('');
    box.dataset.key=key;if(bottom||first)box.scrollTop=box.scrollHeight;
  }
  const blocked=room.phase==='question';
  $('chat-hint').textContent=blocked?'Чат откроется после закрытия вопроса. Ответ отправляется через поле выше и скрыт от соперников.':'Обсуждайте вопрос и результаты здесь.';
  $('chat-text').disabled=blocked;$('chat-send').disabled=blocked;
}

function apply(s){
  if(room&&s.code===room.code&&s.version<room.version)return;
  const oldQuestion=room?.code+':'+room?.active;
  room=s;offset=s.server_time*1000-Date.now();sessionStorage.setItem('room',s.code);
  show('home',false);show('game',true);
  $('room-code').textContent=s.code;
  $('phase').textContent=(s.practice?'Тренировка · ':'')+({event:'Событие',lobby:'Ожидание игроков',question:'Все пишут ответы',review:'Ведущий проверяет ответы',reveal:'Результаты вопроса',ready:'Готовы продолжить',finished:'Квиз завершён'}[s.phase]||'');
  $('players').innerHTML=[...s.players].sort((a,b)=>(a.id===s.host)-(b.id===s.host)||b.score-a.score).map(p=>`<div class="player ${p.id===auth.user.id?'me':''}"><span>${esc(p.name)}</span>${p.id===s.host?'<em>Ведущий</em>':`<strong>${p.score}</strong><em>${s.phase==='question'&&s.answered_ids.includes(p.id)?'Ответ отправлен ✓':p.synthetic?'Искусственный игрок':'очков'}</em>${effectBadge(s,p.id)}`}</div>`).join('');
  show('invite',!s.practice);show('lobby',s.phase==='lobby');show('start',isHost());$('start').disabled=uploading||s.players.length<2||!s.question_count;
  $('pack-count').textContent=`В игре ${s.question_count} вопросов, ${s.round_count} раундов.`;show('waiting',!isHost());show('editor',isHost()&&s.phase==='lobby');
  show('question-list',isHost()&&s.phase==='lobby'&&!!s.question_count);
  $('question-list').innerHTML=(s.question_list||[]).map((q,i)=>`<p>${i+1}. ${esc(q.type==='event'?'⚡ '+q.title:q.text)}${q.media?' · '+({image:'🖼',video:'🎬',audio:'🎧'}[q.media.kind]):''}</p>`).join('');
  show('event',s.phase==='event');
  if(s.phase==='event'){const e=s.event;$('event-title').textContent=e.event_title;$('event-text').textContent=e.text;$('effect-title').textContent=e.title;$('effect-description').textContent=e.description;$('effect-targets').textContent='Получатели: '+e.targets.join(', ')+' · действует '+e.questions+' вопросов';show('event-next',hasControls());}
  const q=s.question;
  if(!q)renderMedia(null);show('question',!!q&&s.phase!=='finished');
  if(q){
    $('category').textContent=`Вопрос ${s.question_number}/${s.question_count} · ${q.category}`;$('value').textContent=q.value+' очков';$('question-text').textContent=q.text;
    $('answer-count').textContent=`Ответили ${s.answered_ids.length} из ${s.players.length-1}`;
    show('answer-form',canAnswer());show('my-answer',!isHost()&&!!ownAnswer()&&s.phase==='question');
    $('my-answer').textContent=ownAnswer()?'Твой ответ: '+ownAnswer().text+' · отправлен':'';
    show('solution',!!q.answer);$('solution').textContent=q.answer?'Правильный ответ: '+q.answer:'';
    show('close',hasControls()&&s.phase==='question');show('next',hasControls()&&s.phase==='reveal');
    $('next').textContent=s.round_number===s.round_count?'Показать итоги →':'Следующий вопрос →';
    if(oldQuestion!==s.code+':'+s.active){$('answer-text').value='';}
    renderMedia(q);renderReview();
  }
  show('ready',s.phase==='ready'&&hasControls());show('finished',s.phase==='finished');show('finish',hasControls()&&['reveal','event'].includes(s.phase));
  $('another').textContent=s.practice?'Ещё одна тренировка':'Новая комната';
  if(s.phase==='finished'){const players=s.players.filter(p=>p.id!==s.host),top=Math.max(...players.map(p=>p.score));$('winner').textContent=players.filter(p=>p.score===top).map(p=>p.name).join(', ')+' — '+top+' очков';}
  renderChat();tick();
}
function tick(){if(!room)return;const n=room.deadline?Math.max(0,Math.ceil((room.deadline*1000-Date.now()-offset)/1000)):null;$('timer').textContent=n===null?'':n?`Осталось ${n} сек.`:'Время вышло. Приём ответов закрывается.';$('answer-send').disabled=n===0;}
setInterval(tick,250);
function connect(code){
  clearTimeout(retry);if(socket){socket.onclose=null;socket.close();}
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${code}`);socket=ws;
  ws.onopen=()=>{ws.send(JSON.stringify({token:auth.token}));$('connection').textContent='● На связи';};
  ws.onmessage=e=>{try{apply(JSON.parse(e.data));}catch{notice('Не удалось обновить игру');}};
  ws.onerror=()=>$('connection').textContent='Нет связи';
  ws.onclose=e=>{if(socket!==ws)return;$('connection').textContent='Переподключение…';if(e.code===1008){notice('Сессия истекла. Перезагрузите приложение.');return;}retry=setTimeout(()=>connect(code),1500);};
}
async function join(code){const s=await api('/rooms/'+encodeURIComponent(code.trim().toUpperCase())+'/join',{});apply(s);connect(s.code);}
async function create(){const s=await api('/rooms',{pack:$('pack').value});await join(s.code);}
async function practice(){const s=await api('/practice',{pack:$('pack').value});apply(s);connect(s.code);}
async function command(action,extra={}){apply(await api('/rooms/'+room.code+'/action',{action,...extra}));}
async function refreshPacks(){const data=await api('/packs'),selected=$('pack').value;$('pack').querySelectorAll('[data-library]').forEach(n=>n.remove());for(const p of data.packs){const o=document.createElement('option');o.value=p.id;o.dataset.library='1';o.textContent=p.title+' · '+p.questions+' вопросов, '+p.count+' раундов';$('pack').append(o);}if([...$('pack').options].some(o=>o.value===selected))$('pack').value=selected;$('pack-errors').textContent=data.errors.map(e=>e.folder+': '+e.error).join('; ');}
$('reload-packs').onclick=guard(refreshPacks);$('event-next').onclick=guard(()=>command('next'));
async function entered(){await refreshPacks();sessionStorage.setItem('auth',JSON.stringify(auth));$('identity').textContent=auth.user.name;show('login',false);show('home',true);const p=new URLSearchParams(location.search),code=tg?.initDataUnsafe?.start_param||p.get('tgWebAppStartParam')||p.get('room')||sessionStorage.getItem('room');if(code&&/^[A-Z2-9]{6}$/i.test(code)){try{await join(code);}catch(e){notice(e.message);sessionStorage.removeItem('room');}}}
$('login-form').onsubmit=guard(async()=>{auth=await api('/login',{name:$('name').value});await entered();});
$('join-form').onsubmit=guard(()=>join($('code').value));$('create').onclick=guard(create);$('practice').onclick=guard(practice);$('another').onclick=guard(()=>room?.practice?practice():create());
for(const a of ['start','close','next'])$(a).onclick=guard(()=>command(a));$('resume').onclick=guard(()=>command('next'));
$('answer-form').onsubmit=guard(()=>command('answer',{text:$('answer-text').value}));
$('review-list').onclick=guard(async e=>{const b=e.target.closest('[data-verdict]');if(b)await command(b.dataset.verdict,{player:b.dataset.player});});
$('chat-form').onsubmit=guard(async()=>{const text=$('chat-text').value;await command('message',{text});if($('chat-text').value===text)$('chat-text').value='';});
$('finish').onclick=guard(async()=>{if(confirm('Завершить квиз и показать итоговый счёт?'))await command('finish');});
$('leave').onclick=()=>{clearTimeout(retry);if(socket){socket.onclose=null;socket.close();socket=null;}sessionStorage.removeItem('room');room=null;$('media-content').replaceChildren();mediaKey='';show('game',false);show('home',true);notice('');history.replaceState(null,'',location.pathname);};
$('q-kind').onchange=()=>{const kind=$('q-kind').value;show('file-fields',!!kind);show('clip-fields',kind==='audio'||kind==='video');$('q-file').accept=kind==='image'?'.png,.jpg,.jpeg,.gif,.webp':kind==='audio'?'.mp3,.wav,.ogg,.m4a':'.mp4,.webm';$('q-file').required=!!kind;};
$('question-form').onsubmit=guard(async()=>{
  if(uploading)return;
  const body={text:$('q-text').value,answer:$('q-answer').value,value:Number($('q-value').value),seconds:Number($('q-seconds').value),clip_start:Number($('clip-start').value||0),clip_end:$('clip-end').value?Number($('clip-end').value):null};
  const kind=$('q-kind').value,file=$('q-file').files[0];
  if(kind&&(!file||file.size>25*1024*1024))throw new Error('Выберите файл размером до 25 МБ');
  if(body.clip_end!=null&&body.clip_end<=body.clip_start)throw new Error('Конец отрывка должен быть позже начала');
  uploading=true;$('add-question').disabled=true;$('start').disabled=true;
  try{
    if(kind){const r=await fetch(`/api/rooms/${room.code}/media?kind=${kind}`,{method:'POST',headers:{Authorization:'Bearer '+auth.token,'Content-Type':file.type||'application/octet-stream'},body:file});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Не удалось загрузить файл');body.media_id=data.id;}
    apply(await api('/rooms/'+room.code+'/questions',body));$('question-form').reset();$('q-kind').onchange();notice('Вопрос добавлен в конец пакета.');
  }finally{uploading=false;$('add-question').disabled=false;if(room)$('start').disabled=room.players.length<2||!room.question_count;}
});
$('invite').onclick=guard(async()=>{const link=config.bot_username?`https://t.me/${config.bot_username}?start=${room.code}`:`${location.origin}/?room=${room.code}`;if(tg?.initData&&config.bot_username)tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent('Крысиные бега! Код: '+room.code)}`);else if(navigator.clipboard){await navigator.clipboard.writeText(link);notice('Ссылка скопирована. Код: '+room.code);}else notice('Код комнаты: '+room.code);});
window.addEventListener('online',()=>{if(room)connect(room.code);});document.addEventListener('visibilitychange',()=>{if(!document.hidden&&room)connect(room.code);});
guard(async()=>{tg?.ready();tg?.expand();config=await api('/config');try{auth=JSON.parse(sessionStorage.getItem('auth'));}catch{auth=null;}if(auth){try{auth.user=await api('/me');}catch{auth=null;sessionStorage.removeItem('auth');}}if(!auth&&tg?.initData)auth=await api('/login',{init_data:tg.initData});if(auth)await entered();else if(config.dev_mode)show('login',true);else notice('Откройте игру через Telegram-бота.');})();
