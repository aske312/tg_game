function countLabel(n,words) {const mod=n%100;return n+' '+words[mod>=11&&mod<=14?2:n%10===1?0:n%10>=2&&n%10<=4?1:2];}
const $ = id => document.getElementById(id);
const tg = window.Telegram?.WebApp;
const displayPage = location.pathname === '/display' || location.pathname === '/display/';
const show = (id, visible) => $(id).hidden = !visible;
const notice = (text, type='info') => { $('notice').textContent = text || ''; $('notice').dataset.type = type; };
const esc = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let auth, config, room, socket, retry, offset = 0, mediaKey = '', uploading = false, libraryPacks = [];
let entryRole = 'player', reactionRoom = '', lastReaction = 0, reactionSentAt = 0;
const isDisplay = () => room?.display === true;
const isPlayer = () => !isHost() && !isDisplay();
const modeTitles={blitz:'Блиц',grid:'Сетка вопросов',binary:'Выбор из двух'};

function renderModes() {
  const stage=room.stage;
  show('stage-banner',!isPlayer()&&!!stage&&!['lobby','finished'].includes(room.phase));
  if(stage){$('stage-mode').textContent=`Раунд ${room.stage_number} / ${room.stage_count} · ${modeTitles[stage.type]}`;$('stage-name').textContent=stage.title;$('stage-hint').textContent=stage.type==='grid'?'Выбираем тему и стоимость, затем все отвечают.':stage.type==='binary'?'Два варианта. Одна попытка. Проверка автоматически.':stage.order==='random'?'Вопросы в случайном порядке.':'Вопросы идут один за другим.';}
  const boardVisible=stage?.type==='grid'&&['board','reveal'].includes(room.phase)&&!room.stage_complete&&(!isPlayer()||room.can_pick);
  show('question-board',boardVisible);
  if(isPlayer()&&boardVisible)show('question',false);
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
function isHost() {return !isDisplay() && room?.host===auth.user.id;}
function hasControls() {return !isDisplay() && (isHost() || (room?.practice && room.owner===auth.user.id));}
function canAnswer() {return room?.phase==='question' && !room.paused && isPlayer() && !ownAnswer();}
function effectBadge(s, uid, future=false) {
  const current=['question','review','reveal'].includes(s.phase)&&!future;
  const active=(current?s.round_modifiers:s.modifiers)?.[uid];
  if(!active)return '';
  const effects={double_reward:['⚡','Двойная награда','За верный ответ — двойная стоимость.'],shield:['🛡️','Защита от штрафа','За ошибку очки не снимаются.'],half_reward:['🪤','Половина награды','За верный ответ — половина стоимости.'],double_penalty:['⚠️','Двойной штраф','За ошибку снимается двойная стоимость.'],reward_multiplier:['⚡','Множитель награды',`Награда ×${active.factor}.`],reward_reduction:['🪤','Уменьшение награды',`Награда ×${active.factor}.`],penalty_multiplier:['⚠️','Множитель штрафа',`Штраф ×${active.factor}.`],bonus_points:['✨','Бонус',`За верный ответ дополнительно +${active.amount}.`],penalty_points:['⚠️','Дополнительный штраф',`За ошибку дополнительно −${active.amount}.`]};
  const [icon,title,description]=effects[active.kind]||['✳','Эффект события',''];
  const timing=current&&s.phase!=='question'?'В этом вопросе':`${future&&['review','reveal'].includes(s.phase)?'Далее · ':''}${countLabel(active.remaining,['вопрос','вопроса','вопросов'])}${current?' · включая текущий':''}`;
  const debuff=['half_reward','double_penalty','reward_reduction','penalty_multiplier','penalty_points'].includes(active.kind);
  return `<small class="effect-badge ${debuff?'debuff':'buff'}" title="${esc(description)}"><span aria-hidden="true">${icon}</span> <strong>${esc(active.title||title)}</strong><span>${esc(description)} ${esc(timing)}</span></small>`;
}

function renderManagement() {
  show('host-management',isHost()&&room.phase!=='finished');
  const players=room.players.filter(p=>p.id!==room.host),select=$('manage-player');
  const key=JSON.stringify(players.map(p=>[p.id,p.name]));
  if(select.dataset.players!==key){
    const previous=select.value;
    select.innerHTML=players.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
    if(players.some(p=>p.id===previous))select.value=previous;
    select.dataset.players=key;
  }
  const target=players.find(p=>p.id===select.value);
  $('managed-score').textContent=target?`Счёт: ${target.score}`:'Пока нет игроков';
  $('managed-effect').innerHTML=target?(effectBadge(room,target.id,true)||'Нет активного эффекта'):'';
  $('effect-timing').textContent=['review','reveal'].includes(room.phase)?'Изменения эффекта действуют со следующего вопроса. Начисленные очки сохраняются.':room.phase==='question'?'Эффект действует сразу, включая текущий вопрос. Новый эффект заменяет прежний.':'Эффект действует со следующего вопроса. Новый эффект заменяет прежний.';
  for(const id of ['adjust-score','apply-effect','clear-effect'])$(id).disabled=!target;
  const badge=isPlayer()&&room.phase!=='finished'?effectBadge(room,auth.user.id):'';
  const upcoming=isPlayer()&&['review','reveal'].includes(room.phase)?effectBadge(room,auth.user.id,true):'';
  show('my-effects',!!(badge||upcoming));
  $('my-effect-list').innerHTML=badge+upcoming;
  show('skip-stage',isHost()&&!['lobby','finished'].includes(room.phase));
  $('skip-stage').textContent=room.stage_number===room.stage_count?'Пропустить раунд и к итогам':'Пропустить раунд →';
}

function mediaTime(seconds) {
  const total=Math.max(0,Math.floor(seconds||0));
  return `${Math.floor(total/60)}:${String(total%60).padStart(2,'0')}`;
}

function clipAudio(node,m) {
  const wrapper=document.createElement('div');wrapper.className='clip-player';
  const controls=document.createElement('div');controls.className='clip-buttons';
  const button=(label,action)=>{const b=document.createElement('button');b.type='button';b.textContent=label;b.className='secondary small';b.onclick=action;controls.append(b);return b;};
  const start=Number(m.start)||0;
  let end=start,ready=false;
  const seek=document.createElement('input');seek.type='range';seek.min=0;seek.max=0;seek.step=.1;seek.value=0;seek.disabled=true;seek.setAttribute('aria-label','Позиция в отрывке');
  const time=document.createElement('span');time.className='clip-time';
  const toggle=button('▶ Воспроизвести',async()=>{
    if(!ready)return;
    if(!node.paused){node.pause();return;}
    if(node.currentTime<start||node.currentTime>=end-.05)node.currentTime=start;
    try{await node.play();}catch{notice('Не удалось воспроизвести аудио. Нажмите ещё раз.','error');}
  });toggle.disabled=true;
  const jump=delta=>{if(ready){node.currentTime=Math.min(end,Math.max(start,node.currentTime+delta));update();}};
  const back=button('−5 сек.',()=>jump(-5)),forward=button('+5 сек.',()=>jump(5));back.disabled=true;forward.disabled=true;
  const update=()=>{
    const position=Math.min(Math.max(0,node.currentTime-start),end-start);
    seek.value=position;time.textContent=`${mediaTime(position)} / ${mediaTime(end-start)}`;
    seek.setAttribute('aria-valuetext',time.textContent);
    toggle.textContent=node.paused?'▶ Воспроизвести':'Ⅱ Пауза';
  };
  const metadata=()=>{
    if(!Number.isFinite(node.duration))return;
    end=Math.min(m.end==null?node.duration:Number(m.end),node.duration);
    ready=end>start;
    seek.disabled=toggle.disabled=back.disabled=forward.disabled=!ready;
    if(!ready){notice('Отрывок за пределами записи.','error');return;}
    seek.max=end-start;node.currentTime=start;update();
    $('media-caption').textContent='Аудиоотрывок · '+mediaTime(end-start);
  };
  seek.oninput=()=>{if(ready){node.currentTime=start+Number(seek.value);update();}};
  node.addEventListener('loadedmetadata',metadata);
  node.addEventListener('durationchange',()=>{if(!ready)metadata();});
  node.addEventListener('timeupdate',()=>{if(ready&&node.currentTime>=end){node.pause();if(node.currentTime>end)node.currentTime=end;}update();});
  node.addEventListener('seeking',()=>{if(ready&&(node.currentTime<start||node.currentTime>end))node.currentTime=Math.min(end,Math.max(start,node.currentTime));});
  node.addEventListener('play',()=>{if(!ready){node.pause();return;}if(node.currentTime<start||node.currentTime>=end)node.currentTime=start;update();});
  for(const event of ['pause','ended'])node.addEventListener(event,update);
  const volume=document.createElement('input');volume.type='range';volume.min=0;volume.max=1;volume.step=.05;volume.value=1;volume.setAttribute('aria-label','Громкость');volume.oninput=()=>{node.volume=Number(volume.value);};
  const volumeLabel=document.createElement('label');volumeLabel.className='clip-volume';volumeLabel.textContent='Громкость';volumeLabel.append(volume);
  node.hidden=true;node.controls=false;time.textContent='Загрузка аудио…';
  wrapper.append(node);wrapper.append(controls);wrapper.append(seek);wrapper.append(time);wrapper.append(volumeLabel);
  return wrapper;
}

function renderMedia(q) {
  const m=q?.media;
  const key=room.code+':'+q?.id+':'+JSON.stringify(m);
  if(key===mediaKey)return;
  mediaKey=key;
  $('media-content').querySelector('audio,video')?.pause();
  $('media-content').replaceChildren();$('media-caption').textContent='';
  if(!m)return;
  const node=document.createElement(m.kind==='image'?'img':m.kind);
  node.src=m.url;
  node.onerror=()=>notice('Не удалось открыть материал. Проверьте формат файла или обновите игру.','error');
  if(m.kind==='image')node.alt='Материал к вопросу';
  else {
    node.controls=true;node.preload='metadata';
    if(m.kind==='audio'){$('media-content').append(clipAudio(node,m));return;}
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
  const visible=isHost()&&['review','reveal','finished'].includes(room.phase);
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
  const pack=libraryPacks.find(p=>p.id===(id==='demo'?'library-demo-quiz':id));
  if(!pack)return;
  $('pack-title').textContent=pack.title;
  $('pack-description').textContent=pack.description||'Готовая игра для тебя и твоей компании.';
  const tags=[countLabel(pack.questions,['вопрос','вопроса','вопросов']),countLabel(pack.stages?.length||1,['раунд','раунда','раундов']),...[...new Set((pack.stages||[]).map(s=>modeTitles[s.type]))]];
  $('pack-tags').innerHTML=tags.map(t=>`<span>${esc(t)}</span>`).join('');
  $('practice').disabled=false;
  $('player-practice').disabled=false;
  $('practice-caption').textContent='Ты ведущий. Боты отвечают, ты проверяешь и управляешь игрой.';
}

function setRole(role) {
  role=role==='host'?'host':'player';
  entryRole=role;
  for(const button of document.querySelectorAll('[data-role]'))button.setAttribute('aria-pressed',String(button.dataset.role===role));
  show('host-entry',role==='host');show('join-panel',role!=='host');
  $('entry-eyebrow').textContent='ВХОД В ИГРУ';
  $('entry-title').textContent='Тебя уже ждут';
  $('entry-hint').textContent='Введи ID комнаты от ведущего.';
  $('join-submit').textContent='Присоединиться →';
  if(role==='host'&&!libraryPacks.length)guard(refreshPacks)();
}
for(const button of document.querySelectorAll('[data-role]'))button.onclick=()=>setRole(button.dataset.role);
function renderReactions() {
  const list=room.reactions||[];
  if(reactionRoom!==room.code){reactionRoom=room.code;lastReaction=0;$('reaction-stream').replaceChildren();}
  for(const reaction of list){
    if(reaction.id<=lastReaction)continue;
    lastReaction=reaction.id;
    if(Date.now()+offset-reaction.time*1000>5000)continue;
    const item=document.createElement('span');item.textContent=reaction.emoji;
    $('reaction-stream').append(item);setTimeout(()=>item.remove(),4000);
  }
}

function apply(s){
  if(room&&s.code===room.code&&s.version<room.version)return;
  const unchanged=room&&s.code===room.code&&s.display===room.display&&(s.ui_version??s.version)===(room.ui_version??room.version);
  const oldQuestion=room?.code+':'+room?.active;
  room=s;offset=s.server_time*1000-Date.now();sessionStorage.setItem(displayPage?'displayRoom':'room',s.code);
  if(unchanged){renderReactions();tick();return;}
  $('game').dataset.phase=s.phase;
  $('game').dataset.role=isDisplay()?'display':isHost()?'host':'player';
  document.body.dataset.role=$('game').dataset.role;
  show('display-entry',false);show('display-fullscreen',displayPage&&isDisplay());
  $('leave').textContent=displayPage?'← Подключить другую комнату':'← На главную';
  show('display-invite',isHost());
  if(isHost()){
    $('display-url').href=(location.origin||'')+'/display?room='+encodeURIComponent(s.code);
    $('display-address').textContent=(location.origin||'')+'/display';$('display-room-code').textContent=s.code;
  }
  $('room-footer').textContent='Комната '+s.code;
  show('scoreboard',!isPlayer());show('reactions',!isDisplay());
  $('lobby-title').textContent=isHost()?'Все на месте?':isDisplay()?'Клан собирается':'Ты в игре';
  if(s.host_practice)$('lobby-title').textContent='Ты — ведущий';
  show('home',false);show('game',true);
  $('room-code').textContent=s.code;
  $('phase').textContent=(s.practice?'Тренировка · ':'')+({board:'Выбираем вопрос',event:'Событие',lobby:'Ожидание игроков',question:s.question?.choices?'Выбираем вариант':'Все пишут ответы',review:'Ведущий проверяет ответы',reveal:'Результаты вопроса',ready:'Готовы продолжить',finished:'Квиз завершён'}[s.phase]||'');
  if(!isPlayer())renderPlayers(s);else $('players').replaceChildren();
  show('round-status',s.phase!=='lobby');
  $('round-label').textContent=`Раунд ${s.stage_number} / ${s.stage_count} · Вопрос ${s.question_number} / ${s.question_count}`;
  $('round-progress').max=Math.max(1,s.round_count);$('round-progress').value=s.used.length;
  show('invite',isHost()&&!s.practice);show('lobby',s.phase==='lobby');show('start',isHost());$('start').disabled=uploading||s.players.length<2||!s.question_count;
  $('pack-count').textContent=`В игре ${s.question_count} вопросов, ${s.stage_count} игровых раундов: ${s.stages.map(stage=>modeTitles[stage.type]).join(' → ')}.`;show('waiting',!isHost());show('editor',isHost()&&s.phase==='lobby');
  if(s.host_practice)$('pack-count').textContent+=' Три бота уже в комнате. Запусти игру, дождись их ответов и оцени их сам. В сетке выбирай за бота, если ход достался ему.';
  if(s.phase==='lobby'){const selected=$('q-stage').value;$('q-stage').innerHTML=s.stages.map(stage=>`<option value="${esc(stage.id)}">${esc(stage.title)} · ${modeTitles[stage.type]}</option>`).join('');if(s.stages.some(stage=>stage.id===selected))$('q-stage').value=selected;renderQuestionEditor();}
  show('question-list-panel',isHost()&&s.phase==='lobby'&&!!s.question_count);
  $('question-list').innerHTML=(s.question_list||[]).map((q,i)=>`<p><span class="question-list-number">${String(i+1).padStart(2,'0')}</span><span class="question-list-text">${esc(q.type==='event'?'✳ '+q.title:q.text)}${q.media?' · '+({image:'Изображение',video:'Видео',audio:'Аудио'}[q.media.kind]):''}</span></p>`).join('');
  show('event',s.phase==='event');
  if(s.phase==='event'){const e=s.event;$('event-title').textContent=e.event_title;$('event-text').textContent=e.text;$('effect-title').textContent=e.title;$('effect-description').textContent=e.description;$('effect-targets').textContent='Получатели: '+e.targets.join(', ')+' · действует '+countLabel(e.questions,['вопрос','вопроса','вопросов']);show('event-next',hasControls());}
  const q=s.question;
  if(!q||s.phase==='finished')renderMedia(null);show('question',!!q&&s.phase!=='finished');
  if(q){
    $('category').textContent=`Вопрос ${s.question_number}/${s.question_count} · ${q.category}`;$('value').textContent=q.value+' очков';$('question-text').textContent=q.text;
    $('answer-count').textContent=`Ответили ${s.answered_ids.length} из ${s.players.length-1}`;
    show('answer-form',canAnswer()&&!q.choices);show('my-answer',isPlayer()&&!!ownAnswer()&&s.phase==='question');
    $('my-answer').textContent=ownAnswer()?'Твой ответ: '+ownAnswer().text+' · отправлен':'';
    show('solution',!!q.answer);$('solution').textContent=q.answer?'Правильный ответ: '+q.answer:'';
    show('close',hasControls()&&s.phase==='question');show('next',hasControls()&&s.phase==='reveal');
    $('next').textContent=s.round_number===s.round_count?'Показать итоги →':s.stage_complete?'Следующий раунд →':s.stage?.type==='grid'?'Вернуться к сетке →':'Следующий вопрос →';
    if(oldQuestion!==s.code+':'+s.active){$('answer-text').value='';}
    if(s.phase!=='finished')renderMedia(q);renderReview();
  }
  renderHostAnswers();renderModes();renderManagement();
  show('ready',s.phase==='ready'&&hasControls());show('finished',s.phase==='finished');show('finish',hasControls()&&['reveal','event','board'].includes(s.phase));
  show('another',!isDisplay());
  $('another').textContent=isPlayer()&&!s.practice?'На главный экран':s.practice?'Ещё одна тренировка':'Новая комната';
  renderExperience();
  renderReactions();tick();
}
function tick(){
  if(!room)return;
  const now=room.paused?room.paused_at*1000:Date.now()+offset;
  const left=room.deadline?Math.max(0,room.deadline*1000-now):null;
  const n=left===null?null:Math.ceil(left/1000),urgent=n!==null&&n<=10;
  $('timer').textContent=n===null?'':n===0?'Время вышло':`${n} сек.`;
  $('timer').dataset.urgent=urgent;$('timer-track').dataset.urgent=urgent;
  show('timer-track',n!==null);
  $('timer-bar').style.width=(left===null?0:Math.min(100,left/(room.question?.seconds||45)/10))+'%';
  $('answer-send').disabled=n===0||room.paused;
  for(const button of $('binary-options').querySelectorAll('button'))button.disabled=!canAnswer()||n===0;
  if(room.advance_at)$('auto-next').textContent=`Следующий вопрос через ${Math.max(0,Math.ceil((room.advance_at*1000-Date.now()-offset)/1000))} сек.`;
  tickExperience();
}
setInterval(tick,250);
function connect(code){
  clearTimeout(retry);if(socket){socket.onclose=null;socket.close();}
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${code}`);socket=ws;
  ws.onopen=()=>{ws.send(JSON.stringify({token:auth.token,display:isDisplay()}));$('connection').textContent='● На связи';$('connection').dataset.status='online';};
  ws.onmessage=e=>{if(socket!==ws)return;try{apply(JSON.parse(e.data));}catch{notice('Не удалось обновить игру','error');}};
  ws.onerror=()=>{$('connection').textContent='Нет связи';$('connection').dataset.status='offline';};
  ws.onclose=e=>{if(socket!==ws)return;$('connection').textContent='Переподключение…';$('connection').dataset.status='offline';if(e.code===1008){if(displayPage){retry=setTimeout(()=>guard(()=>connectDisplay(code))(),1500);return;}notice('Сессия истекла. Перезагрузите приложение.','error');return;}retry=setTimeout(()=>connect(code),1500);};
}
async function join(code){const s=await api('/rooms/'+encodeURIComponent(code.trim().toUpperCase())+'/join',{});apply(s);connect(s.code);}
async function connectDisplay(code){
  const result=await api('/display',{code:code.trim().toUpperCase()});
  auth={token:result.token,user:result.user};
  apply(result.state);connect(result.state.code);
  history.replaceState(null,'','/display?room='+encodeURIComponent(result.state.code));
}
async function create(){const s=await api('/rooms',{pack:$('pack').value});await join(s.code);}
async function practice(role='host',pack=$('pack').value){const s=await api('/practice',{pack,role});apply(s);connect(s.code);}
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
$('pause-game').onclick=guard(()=>command('pause'));
$('continue-game').onclick=guard(()=>command('unpause'));
$('show-scores').onclick=guard(()=>command('show_scores'));
$('hide-scores').onclick=guard(()=>command('hide_scores'));
$('scores-next').onclick=guard(()=>command('next'));
$('skip-intro').onclick=guard(()=>command('next'));
$('manage-player').onchange=renderManagement;
$('score-form').onsubmit=guard(()=>command('adjust_score',{player:$('manage-player').value,delta:Number($('score-delta').value)}));
$('effect-form').onsubmit=guard(()=>command('set_effect',{player:$('manage-player').value,effect:{type:$('manage-effect').value,questions:Number($('effect-duration').value)}}));
$('clear-effect').onclick=guard(()=>command('clear_effect',{player:$('manage-player').value}));
$('skip-stage').onclick=guard(async()=>{
  if(window.confirm(`Пропустить раунд «${room.stage.title}»? Неоценённые ответы и оставшиеся вопросы не принесут очков. Уже начисленные очки сохранятся.`))await command('skip_stage');
});
$('enable-sound').onclick=async()=>{if(await unlockSound())fanfare();};
async function entered(){setRole('player');sessionStorage.setItem('auth',JSON.stringify(auth));$('identity').textContent=auth.user.name;show('login',false);show('home',true);const p=new URLSearchParams(location.search),code=tg?.initDataUnsafe?.start_param||p.get('tgWebAppStartParam')||p.get('room')||sessionStorage.getItem('room');if(code&&/^[A-Z2-9]{6}$/i.test(code)){try{await join(code);}catch(e){notice(e.message);sessionStorage.removeItem('room');}}}
$('display-form').onsubmit=guard(()=>connectDisplay($('display-code').value));
$('copy-display-url').onclick=guard(async()=>{
  const link=$('display-url').href;
  if(navigator.clipboard){await navigator.clipboard.writeText(link);notice('Ссылка для общего экрана скопирована.');}
  else notice('Открой на компьютере: '+link);
});
$('display-fullscreen').onclick=guard(async()=>{
  if(document.fullscreenElement)await document.exitFullscreen();
  else if(document.documentElement.requestFullscreen)await document.documentElement.requestFullscreen();
  else notice('Используй полноэкранный режим браузера.');
});
$('login-form').onsubmit=guard(async()=>{auth=await api('/login',{name:$('name').value});await entered();});
$('join-form').onsubmit=guard(()=>join($('code').value));$('create').onclick=guard(create);$('practice').onclick=guard(()=>practice('host'));$('player-practice').onclick=guard(()=>practice('player'));$('another').onclick=guard(()=>room?.practice?practice(room.host_practice?'host':'player',room.pack_id):isHost()?create():$('leave').click());
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
$('reaction-buttons').onclick=async event=>{
  const button=event.target.closest('[data-reaction]'),now=Date.now();
  if(!button||now-reactionSentAt<1000)return;
  reactionSentAt=now;
  try{await command('reaction',{text:button.dataset.reaction});}catch{/* Reactions are optional and never interrupt the game. */}
};
$('finish').onclick=guard(async()=>{if(confirm('Завершить квиз и показать итоговый счёт?'))await command('finish');});
$('leave').onclick=()=>{clearTimeout(retry);if(socket){socket.onclose=null;socket.close();socket=null;}sessionStorage.removeItem(displayPage?'displayRoom':'room');sessionStorage.removeItem('roomRole');delete document.body.dataset.role;room=null;resetExperience();$('media-content').querySelector('audio,video')?.pause();$('media-content').replaceChildren();mediaKey='';show('game',false);show('home',!displayPage);show('display-entry',displayPage);if(displayPage)auth=null;else setRole('player');notice('');history.replaceState(null,'',location.pathname);};
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
  if(displayPage){
    $('identity').textContent='Общий экран';$('brand-link').href='/display';
    show('display-entry',true);
    const code=new URLSearchParams(location.search).get('room')||sessionStorage.getItem('displayRoom');
    if(code){$('display-code').value=code.toUpperCase();await connectDisplay(code);}
    return;
  }
  tg?.ready();tg?.expand();config=await api('/config');
  try{auth=JSON.parse(sessionStorage.getItem('auth'));}catch{auth=null;}
  if(auth){try{auth.user=await api('/me');}catch{auth=null;sessionStorage.removeItem('auth');}}
  if(!auth&&tg?.initData){try{auth=await api('/login',{init_data:tg.initData});}catch(e){telegramEntry();throw e;}}
  if(auth)await entered();else if(config.dev_mode)show('login',true);else telegramEntry();
})();
