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
  if(stage){$('stage-mode').textContent=`Раунд ${room.stage_number} / ${room.stage_count} · ${modeTitles[stage.type]}`;$('stage-name').textContent=stage.title;$('stage-hint').textContent=stage.type==='grid'?(stage.answer_mode==='single'?'Отвечает первый нажавший «Ответить».':'Выбираем тему и стоимость, затем все отвечают.'):stage.type==='binary'?'Два варианта. Одна попытка. Проверка автоматически.':stage.order==='random'?'Вопросы в случайном порядке.':'Вопросы идут один за другим.';}
  const boardVisible=stage?.type==='grid'&&['board','reveal'].includes(room.phase)&&!room.stage_complete&&(!isPlayer()||room.can_pick)&&(!isDisplay()||room.phase==='board');
  show('question-board',boardVisible);
  if(isPlayer()&&boardVisible)show('question',false);
  const chooser=room.players.find(p=>p.id===room.chooser);
  $('board-chooser').textContent=room.can_pick?'Выбери следующий вопрос.':`Выбирает ${chooser?.name||'ведущий'}.`;
  const categories=[...new Set((room.board||[]).map(q=>q.category))];
  $('board-cells').innerHTML=categories.map(c=>`<div class="board-row"><div class="board-category">${esc(c)}</div><div class="board-values">${room.board.filter(q=>q.category===c).sort((a,b)=>a.value-b.value).map(q=>`<button data-pick="${esc(q.id)}" ${!room.can_pick||q.used?'disabled':''} class="${q.used?'played':''}" aria-label="${esc(c)}: ${q.value} очков${q.used?', сыгран':''}">${q.used?'—':q.value}</button>`).join('')}</div></div>`).join('');
  const q=room.question,binary=Array.isArray(q?.choices);
  show('binary-options',binary&&room.phase!=='finished');
  $('binary-options').innerHTML=binary?q.choices.map((choice,i)=>`<button data-choice="${i}" ${canAnswer()?'':'disabled'} class="${ownAnswer()?.choice===i?'chosen':''} ${q.correct_choice===i&&(!isDisplay()||!room.display_scene||room.display_scene==='answer')?'correct-option':''} ${ownAnswer()?.choice===i&&ownAnswer()?.verdict==='wrong'?'wrong-option':''}">${esc(choice)}</button>`).join(''):'';
  show('auto-next',!!room.advance_at&&room.phase==='reveal');
}

function renderDisplayPreview() {
  const visible=isDisplay()&&room.phase==='lobby';
  show('display-preview',visible);
  if(!visible)return;
  $('display-preview-title').textContent=room.pack_title||'Крысиные бега';
  $('display-preview-code').textContent=room.code;
  $('display-preview-rounds').textContent=countLabel(room.stage_count,['раунд','раунда','раундов']);
  $('display-preview-questions').textContent=countLabel(room.question_count,['вопрос','вопроса','вопросов']);
  $('display-preview-modes').textContent=[...new Set(room.stages.map(s=>modeTitles[s.type]))].join(' · ');
  const grid=room.stage?.type==='grid'&&(room.board||[]).length>0;
  show('display-preview-grid',grid);
  if(grid){
    $('display-preview-stage').textContent=room.stage.title;
    const categories=[...new Set(room.board.map(q=>q.category))];
    $('display-preview-cells').innerHTML=categories.map(category=>`<div class="preview-board-row"><strong>${esc(category)}</strong><div>${room.board.filter(q=>q.category===category).sort((a,b)=>a.value-b.value).map(q=>`<span>${q.value}</span>`).join('')}</div></div>`).join('');
  }else $('display-preview-cells').replaceChildren();
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
function canAnswer() {return room?.phase==='question' && !room.paused && isPlayer() && !ownAnswer() && room.can_answer!==false;}

function renderPresentation() {
  const scene=room.paused?(room.pause_view==='scores'?'scores':'pause'):room.display_scene||(room.phase==='board'?'board':room.phase==='reveal'?'answer':'question');
  $('game').dataset.scene=scene;
  const active=!['lobby','intro','finished'].includes(room.phase);
  show('presentation-controls',hasControls()&&active);
  $('presentation-status').textContent='На экране: '+({question:'вопрос',answer:'ответ',board:'сетка',scores:'счёт',pause:'перерыв',round_end:'раунд завершён'}[scene]||'вопрос');
  for(const name of ['question','answer','board']){
    const button=$('scene-'+name);
    button.setAttribute('aria-pressed',scene===name?'true':'false');
    button.disabled=!!room.paused||!!room.scores_visible||(name==='answer'&&room.phase!=='reveal')||
      (['question','answer'].includes(name)&&!room.question)||
      (name==='board'&&(room.stage?.type!=='grid'||!['board','reveal'].includes(room.phase)||room.stage_complete));
  }
  show('buzz-answer',isPlayer()&&!!room.can_buzz&&!room.paused);
  $('buzz-answer').disabled=!room.can_buzz||!!room.paused;
  const single=room.stage?.type==='grid'&&room.stage.answer_mode==='single';
  show('responder-status',single&&isPlayer()&&['question','review'].includes(room.phase));
  const responder=room.players.find(p=>p.id===room.responder);
  $('responder-status').textContent=responder?(responder.id===auth.user.id?'Ты нажал первым. Ответь голосом или отправь текст. Ведущий проверит ответ.':`Право ответа: ${responder.name}.`):ownAnswer()?.verdict?'Попытка использована. Остальные игроки продолжают отвечать.':'Первый нажавший «Ответить» получит право ответа.';
  if(isPlayer()&&room.display_scene){
    show('question-board',!!room.practice&&!!room.can_pick&&scene==='board');
    const waiting=room.stage?.type==='grid'&&(room.phase==='board'||(room.phase==='reveal'&&scene==='board'))&&!room.paused&&!room.scores_visible;
    show('board-waiting',waiting&&$('question-board').hidden);
    if(waiting)show('question',false);
    else if(room.question&&!room.paused&&!room.scores_visible&&active&&$('round-end').hidden)show('question',true);
  }
  const scoresOnDisplay=isDisplay()&&room.phase!=='lobby'&&room.phase!=='finished'&&!!room.paused&&room.pause_view==='scores';
  show('presentation-scores',scoresOnDisplay);
  if(scoresOnDisplay){
    for(const id of ['question','question-board','event','ready','stage-banner','board-waiting','pause-panel','round-scores','grid-intro'])show(id,false);
    $('presentation-results').innerHTML=roundScoreTable();
  }
  if(isDisplay()&&active&&!room.paused&&!room.scores_visible){
    show('question',!!room.question&&['question','answer'].includes(scene));
    show('question-board',scene==='board');
    show('solution',scene==='answer'&&!!room.question?.answer);
    show('event',scene==='question'&&room.phase==='event');
  }
}
function effectBadge(s, uid, future=false) {
  const current=['question','review','reveal'].includes(s.phase)&&!future;
  const active=(current?s.round_modifiers:s.modifiers)?.[uid];
  if(!active)return '';
  const effects={double_reward:['⚡','Двойная награда','За верный ответ — двойная стоимость.'],shield:['🛡️','Защита от штрафа','За ошибку очки не снимаются.'],half_reward:['','Половина награды','За верный ответ — половина стоимости.'],double_penalty:['⚠️','Двойной штраф','За ошибку снимается двойная стоимость.'],reward_multiplier:['⚡','Множитель награды',`Награда ×${active.factor}.`],reward_reduction:['','Уменьшение награды',`Награда ×${active.factor}.`],penalty_multiplier:['⚠️','Множитель штрафа',`Штраф ×${active.factor}.`],bonus_points:['✨','Бонус',`За верный ответ дополнительно +${active.amount}.`],penalty_points:['⚠️','Дополнительный штраф',`За ошибку дополнительно −${active.amount}.`]};
  const [,title,description]=effects[active.kind]||['','Эффект события',''];
  const iconName={half_reward:'half',reward_reduction:'half',shield:'shield',double_reward:'bolt',reward_multiplier:'bolt',double_penalty:'warning',penalty_multiplier:'warning',penalty_points:'warning'}[active.kind]||'spark';
  const icon=`<svg class="effect-icon" viewBox="0 0 24 24" aria-hidden="true"><use href="/static/effects.svg#${iconName}"></use></svg>`;
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

function renderMedia(q) { renderQuestionMedia(q); }

function renderReview() {
  const single=room.stage?.type==='grid'&&room.stage.answer_mode==='single'&&!room.single_closed;
  const answers=Object.values(room.answers),checked=answers.filter(a=>a.verdict).length;
  const missed=Object.keys(room.omission_penalties||{}).length;
  show('host-review-status',isHost()&&['review','reveal'].includes(room.phase)&&(answers.length>0||missed>0));
  $('host-review-status').textContent=`Проверено ${checked} из ${answers.length} ответов`+(missed?` · Пропусков: ${missed}, штрафы учтены`:'');
  const visible=isHost()&&(room.phase==='review'||single&&room.phase==='question'&&room.responder);
  $('review-list').innerHTML=visible?'<h3 class="review-heading">Проверить ответ</h3>'+room.players.filter(p=>single?p.id===room.responder&&!room.answers[p.id]?.verdict:room.answers[p.id]&&!room.answers[p.id].verdict).map(p=>{
    const a=room.answers[p.id];
    return `<div class="review-answer" data-verdict="pending"><strong>${esc(p.name)}</strong><p>${esc(a?.text||'Игрок отвечает голосом. Можно оценить без ввода текста.')}</p><div class="inline"><button data-player="${esc(p.id)}" data-question="${esc(room.question.id)}" data-verdict="correct">✓ Верно</button><button class="danger" data-player="${esc(p.id)}" data-question="${esc(room.question.id)}" data-verdict="wrong">✕ Неверно</button></div></div>`;
  }).join(''):'';
}

function renderHostLayout() {
  const controls=hasControls(),active=!['lobby','finished'].includes(room.phase);
  const roundEnd=room.stage_complete&&['reveal','event'].includes(room.phase);
  const intermission=roundEnd&&!room.paused&&(room.display_scene==='round_end'||room.scores_visible);
  show('host-console',controls&&active&&!intermission);
  show('host-options',controls&&room.phase!=='finished');
  show('host-player-count',isHost()&&room.phase==='lobby');
  $('host-player-count').textContent=`Игроков: ${room.players.length-1} / 8`;
  if(!isHost())return;
  show('stage-banner',false);
  $('round-label').textContent=`${room.stage?.title||'Раунд'} · ${room.stage_number}/${room.stage_count} · Вопрос ${room.question_number}/${room.question_count}`;
  const board=room.stage?.type==='grid'&&!room.stage_complete&&
    (room.phase==='board'||(room.phase==='reveal'&&room.display_scene==='board'))&&!room.paused&&!room.scores_visible;
  show('question-board',board);
  if(board)show('question',false);
  show('presentation-controls',active&&room.phase!=='intro'&&!room.paused&&!room.scores_visible);
  show('scene-question',!!room.question&&room.phase==='reveal');
  show('scene-answer',room.phase==='reveal');
  show('scene-board',room.stage?.type==='grid'&&!room.stage_complete&&['board','reveal'].includes(room.phase));
}

function renderHostAnswers() {
  const visible=isHost()&&room.phase==='question';
  const single=room.stage?.type==='grid'&&room.stage.answer_mode==='single';
  show('host-hint',visible);show('host-answers',visible&&!single&&Object.keys(room.answers).length>0);
  $('host-hint').textContent=single?(room.responder?'Таймер остановлен. Оцените устный или письменный ответ.':room.answered_ids.length>=room.players.length-1?'Все игроки использовали попытку. Завершите вопрос.':'Ждём нажатия «Ответить». После ошибки вопрос продолжается.'):(Object.keys(room.answers).length?'Ответы поступили · проверка после закрытия приёма':'Ждём ответы игроков…');
  $('host-answers').innerHTML=visible&&!single?room.players.filter(p=>room.answers[p.id]).map(p=>`<div class="host-answer"><strong>${esc(p.name)}</strong><span>${esc(room.answers[p.id].text)}</span></div>`).join(''):'';
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
  show('reactions',isPlayer());
  $('lobby-title').textContent=isHost()?'Все на месте?':isDisplay()?'Клан собирается':'Ты в игре';
  if(s.host_practice)$('lobby-title').textContent='Ты — ведущий';
  show('home',false);show('game',true);
  $('room-code').textContent=s.code;
  $('phase').textContent=(s.practice?'Тренировка · ':'')+({board:'Выбираем вопрос',event:'Событие',lobby:'Ожидание игроков',question:s.question?.choices?'Выбираем вариант':'Все пишут ответы',review:'Ведущий проверяет ответы',reveal:'Результаты вопроса',ready:'Готовы продолжить',finished:'Квиз завершён'}[s.phase]||'');
  show('round-status',s.phase!=='lobby');
  $('round-label').textContent=`Раунд ${s.stage_number} / ${s.stage_count} · Вопрос ${s.question_number} / ${s.question_count}`;
  $('round-progress').max=Math.max(1,s.round_count);$('round-progress').value=s.used.length;
  show('invite',isHost()&&!s.practice);show('lobby',s.phase==='lobby'&&!isDisplay());show('start',isHost());$('start').disabled=uploading||s.players.length<2||!s.question_count;
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
    $('answer-count').textContent=s.stage?.answer_mode==='single'?`Попыток: ${s.answered_ids.length}`:`Ответили ${s.answered_ids.length} из ${s.players.length-1}`;
    const penalty=s.omission_penalties?.[auth.user.id];
    show('answer-form',canAnswer()&&!q.choices);show('my-answer',isPlayer()&&((!!ownAnswer()&&s.phase==='question')||penalty!==undefined));
    $('my-answer').textContent=penalty!==undefined?`Ответ не отправлен · ${penalty} очков`:ownAnswer()?.verdict==='wrong'?`Ответ неверный · ${ownAnswer().points} очков. Вопрос продолжается для остальных.`:ownAnswer()?'Твой ответ: '+ownAnswer().text+' · отправлен':'';
    show('solution',!!q.answer);$('solution').textContent=q.answer?'Правильный ответ: '+q.answer:'';
    show('close',hasControls()&&s.phase==='question');show('next',hasControls()&&s.phase==='reveal'&&!s.stage_complete);
    const missing=s.players.length-1-s.answered_ids.length,all=s.stage?.type!=='grid'||s.stage.answer_mode!=='single';
    $('close').textContent=all&&missing>0?`Завершить вопрос · без ответа: ${missing}`:'Завершить вопрос';
    show('close-hint',hasControls()&&s.phase==='question'&&all&&missing>0);
    $('next').textContent=s.stage_complete?'Показать счёт раунда →':s.stage?.type==='grid'?'Вернуться к сетке →':'Следующий вопрос →';
    if(oldQuestion!==s.code+':'+s.active){$('answer-text').value='';}
    if(s.phase!=='finished')renderMedia(q);renderReview();
  }
  renderHostAnswers();renderModes();renderManagement();renderDisplayPreview();
  show('ready',s.phase==='ready'&&hasControls());show('finished',s.phase==='finished');show('finish',hasControls()&&['reveal','event','board'].includes(s.phase));
  show('another',!isDisplay());
  $('another').textContent=isPlayer()&&!s.practice?'На главный экран':s.practice?'Ещё одна тренировка':'Новая комната';
  renderExperience();
  renderPresentation();
  renderHostLayout();
  renderDisplaySound();syncMediaPlayback();renderReactions();tick();
}
function tick(){
  if(!room)return;
  const now=room.paused?room.paused_at*1000:Date.now()+offset;
  const held=room.stage?.answer_mode==='single'&&room.responder&&!room.single_closed&&room.buzz_remaining!=null;
  const left=held?room.buzz_remaining*1000:room.deadline?Math.max(0,room.deadline*1000-now):null;
  const n=left===null?null:Math.ceil(left/1000),urgent=n!==null&&n<=10;
  show('timeout-hint',room.phase==='question'&&n===0&&!room.paused);
  $('timeout-hint').textContent=hasControls()?'Время вышло. Завершите вопрос, чтобы перейти к проверке и результатам.':'Время вышло. Дождитесь завершения вопроса ведущим.';
  $('timer').textContent=n===null?'':n===0?'Время вышло':`${n} сек.${held?' · ответ игрока':''}`;
  $('timer').dataset.urgent=urgent;$('timer-track').dataset.urgent=urgent;
  show('timer-track',n!==null);
  $('timer-bar').style.width=(left===null?0:Math.min(100,left/(room.question?.seconds||45)/10))+'%';
  $('answer-send').disabled=n===0||room.paused;
  $('buzz-answer').disabled=n===0||room.paused||!room.can_buzz;
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
$('display-game-scores').onclick=guard(()=>command('display_scores'));
$('continue-game').onclick=guard(()=>command('unpause'));
$('show-scores').onclick=guard(()=>command('show_scores'));
$('hide-scores').onclick=guard(()=>command('hide_scores'));
$('scores-next').onclick=guard(()=>command('next'));
$('round-next').onclick=guard(()=>command('next'));
$('round-results-button').onclick=guard(()=>command('show_scores'));
$('results-back').onclick=guard(()=>command('hide_scores'));
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
for(const name of ['question','answer','board'])$('scene-'+name).onclick=guard(()=>command('display_'+name));
$('buzz-answer').onclick=guard(()=>command('buzz',{question:room.question.id}));
$('display-media-toggle').onclick=guard(async()=>{
  $('display-media-toggle').disabled=true;
  try {await sendMediaAction(mediaTransport().playing?'media_pause':'media_play');}
  finally {renderHostMediaToggle();}
});
$('enable-display-media').onclick=guard(async()=>{
  displaySoundEnabled=true;void unlockSound();renderDisplaySound();
  if(activeClip?.ready)await activeClip.localPlay();
});
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
for(const a of ['start','close'])$(a).onclick=guard(()=>command(a));
$('next').onclick=guard(()=>command(room.stage_complete&&!room.scores_visible?'show_scores':room.stage?.type==='grid'&&!room.stage_complete?'display_board':'next'));$('resume').onclick=guard(()=>command('next'));
$('answer-form').onsubmit=guard(()=>command('answer',{question:room.question.id,text:$('answer-text').value}));
$('binary-options').onclick=guard(async event=>{const b=event.target.closest('[data-choice]');if(b&&!b.disabled)await command('answer',{question:room.question.id,choice:Number(b.dataset.choice)});});
$('board-cells').onclick=guard(async event=>{const b=event.target.closest('[data-pick]');if(b&&!b.disabled)await command('pick',{question:b.dataset.pick});});
const pendingGrades=new Set();
$('review-list').onclick=async e=>{
  const b=e.target.closest('button[data-verdict]');if(!b||pendingGrades.has(b.dataset.player))return;
  const player=b.dataset.player;pendingGrades.add(player);notice('');
  for(const button of $('review-list').querySelectorAll('button'))if(button.dataset.player===player)button.disabled=true;
  try{await command(b.dataset.verdict,{player,question:b.dataset.question});}catch(error){notice(error.message||'Нет связи с сервером','error');}
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
$('q-kind').onchange=()=>{const kind=$('q-kind').value;show('file-fields',!!kind);show('clip-fields',kind==='audio'||kind==='video');$('q-file').accept=kind==='image'?'.png,.jpg,.jpeg,.jfif,.gif,.webp,.avif,.bmp':kind==='audio'?'.mp3,.wav,.ogg,.oga,.opus,.m4a,.aac,.flac':'.mp4,.webm,.mov,.m4v';$('q-file').required=!!kind;};
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
