const $ = id => document.getElementById(id);
const tg = window.Telegram?.WebApp;
let auth, config, room, socket, retry, offset = 0;
const show = (id, visible) => $(id).hidden = !visible;
const notice = message => $('notice').textContent = message || '';
const esc = text => String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path, body) {
  const res = await fetch('/api'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...(auth?{Authorization:'Bearer '+auth.token}:{})},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const data = await res.json();
  if(!res.ok) throw new Error(typeof data.detail==='string'?data.detail:'Проверьте введённые данные');
  return data;
}
function guard(fn) {return async event=>{event?.preventDefault();notice('');try{await fn(event);}catch(e){notice(e.message||'Нет связи с сервером');}};}
function apply(s) {
  if(room && s.code===room.code && s.version<room.version) return;
  room=s;offset=s.server_time*1000-Date.now();sessionStorage.setItem('room',s.code);
  show('home',false);show('game',true);
  const host=s.host===auth.user.id;
  const practiceOwner=s.practice&&s.owner===auth.user.id;
  const controls=host||practiceOwner;
  $('room-code').textContent=s.code;
  $('phase').textContent=(s.practice?'Тренировка · ':'')+{lobby:'Ожидание игроков',board:'Выбираем вопрос',question:'Кто знает ответ?',answer:'Игрок пишет ответ',reveal:'Ответ раскрыт',finished:'Игра завершена'}[s.phase];
  $('players').innerHTML=[...s.players].sort((a,b)=>(a.id===s.host)-(b.id===s.host)||b.score-a.score).map(p=>`<div class="player ${p.id===auth.user.id?'me':''}"><span>${esc(p.name)}</span>${p.id===s.host?'<em>Ведущий</em>':`<strong>${p.score}</strong><em>${p.synthetic?'Искусственный игрок':'очков'}</em>`}</div>`).join('');
  show('invite',!s.practice);
  show('lobby',s.phase==='lobby');show('start',host);$('start').disabled=s.players.length<2;show('waiting',!host);show('board',s.phase==='board');
  if(s.phase==='board') $('board').innerHTML=[...new Set(s.board.map(q=>q.category))].map(c=>`<div class="board-row"><div class="board-category">${esc(c)}</div>${s.board.filter(q=>q.category===c).map(q=>`<button class="cell ${s.used.includes(q.id)?'used':''}" data-question="${q.id}" ${!controls||s.used.includes(q.id)?'disabled':''}>${s.used.includes(q.id)?'—':q.value}</button>`).join('')}</div>`).join('');
  show('question',!!s.question);
  if(s.question) {
    $('category').textContent=s.question.category;$('value').textContent=s.question.value+' очков';$('question-text').textContent=s.question.text;
    const p=s.players.find(p=>p.id===s.buzzer);
    $('answerer').textContent=p?'Отвечает: '+p.name:s.attempted.includes(auth.user.id)?'Ты уже отвечал на этот вопрос.':'';
    show('buzz',!host&&s.phase==='question'&&!s.attempted.includes(auth.user.id));show('judge',host&&s.phase==='answer');show('skip',host&&['question','answer'].includes(s.phase));show('next',controls&&s.phase==='reveal');show('solution',!!s.question.answer);$('solution').textContent=s.question.answer?'Ответ: '+s.question.answer:'';
    if(s.submitted) $('answerer').textContent+=' · Ответ отправлен: '+s.submitted.text;
  }
  show('finish',controls&&!['lobby','finished'].includes(s.phase));show('finished',s.phase==='finished');
  $('another').textContent=s.practice?'Ещё одна тренировка':'Новая комната';
  if(s.phase==='finished') {const players=s.players.filter(p=>p.id!==s.host), top=Math.max(...players.map(p=>p.score));$('winner').textContent=players.filter(p=>p.score===top).map(p=>p.name).join(', ')+' — '+top+' очков';}
  renderChat();tick();
}
function canAnswer(){return room?.phase==='answer'&&room.buzzer===auth.user.id&&!room.submitted;}
function renderChat(){
  const messages=room.messages||[];
  const last=messages.at(-1)?.id||0;
  const key=room.code+':'+last;
  if($('messages').dataset.key!==key){
    const box=$('messages');const nearBottom=box.scrollHeight-box.scrollTop-box.clientHeight<70;
    box.innerHTML=messages.map(m=>`<div class="chat-message ${m.kind==='system'?'system':''} ${m.user_id===auth.user.id?'mine':''}"><strong>${esc(m.name)}${m.kind==='answer'?' · ответ':''}</strong><p>${esc(m.text)}</p></div>`).join('');
    const first=!box.dataset.key||!box.dataset.key.startsWith(room.code+':');box.dataset.key=key;
    if(nearBottom||first)box.scrollTop=box.scrollHeight;
  }
  $('chat-hint').textContent=canAnswer()?'Твоя очередь! Напиши ответ и отправь его до конца таймера.':room.submitted?.user_id===auth.user.id?'Ответ отправлен. Ждём оценку ведущего.':'Общайтесь здесь. Для зачётного ответа сначала нажмите «Я знаю ответ!».';
  $('chat-text').placeholder=canAnswer()?'Твой ответ…':'Написать сообщение…';
  $('chat-send').textContent=canAnswer()?'Ответить':'Отправить';
}
function tick(){if(!room)return;const n=room.deadline?Math.max(0,Math.ceil((room.deadline*1000-Date.now()-offset)/1000)):null;$('timer').textContent=room.submitted?'Ответ отправлен. Ведущий проверяет.':n===null?'':n?`Осталось ${n} сек.`:room.practice?'Время вышло. Робоведущий завершает попытку.':'Время вышло. Ведущий завершает или оценивает ответ.';$('buzz').disabled=n===0;$('correct').disabled=!room.submitted;$('wrong').disabled=!room.submitted&&n!==0;$('chat-send').disabled=canAnswer()&&n===0;}
setInterval(tick,250);
function connect(code) {
  clearTimeout(retry);if(socket){socket.onclose=null;socket.close();}
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/${code}`);socket=ws;
  ws.onopen=()=>{ws.send(JSON.stringify({token:auth.token}));$('connection').textContent='● На связи';};
  ws.onmessage=e=>{try{apply(JSON.parse(e.data));}catch{notice('Не удалось обновить игру');}};
  ws.onerror=()=>$('connection').textContent='Нет связи';
  ws.onclose=e=>{if(socket!==ws)return;$('connection').textContent='Переподключение…';if(e.code===1008){notice('Сессия истекла. Перезагрузите приложение.');return;}retry=setTimeout(()=>connect(code),1500);};
}
async function join(code){const s=await api('/rooms/'+encodeURIComponent(code.trim().toUpperCase())+'/join',{});apply(s);connect(s.code);}
async function create(){const r=await api('/rooms',{});await join(r.code);}
async function practice(){const s=await api('/practice',{});apply(s);connect(s.code);}
async function command(action,question='',text=''){apply(await api('/rooms/'+room.code+'/action',{action,question,text}));}
async function entered(){sessionStorage.setItem('auth',JSON.stringify(auth));$('identity').textContent=auth.user.name;show('login',false);show('home',true);const p=new URLSearchParams(location.search);const code=tg?.initDataUnsafe?.start_param||p.get('tgWebAppStartParam')||p.get('room')||sessionStorage.getItem('room');if(code&&/^[A-Z2-9]{6}$/i.test(code)){try{await join(code);}catch(e){notice(e.message);sessionStorage.removeItem('room');}}}
$('login-form').onsubmit=guard(async()=>{auth=await api('/login',{name:$('name').value});await entered();});
$('join-form').onsubmit=guard(()=>join($('code').value));$('create').onclick=guard(create);$('practice').onclick=guard(practice);$('another').onclick=guard(()=>room?.practice?practice():create());
$('chat-form').onsubmit=guard(async()=>{const input=$('chat-text');const text=input.value;await command(canAnswer()?'answer':'message','',text);if(input.value===text)input.value='';});
$('leave').onclick=()=>{clearTimeout(retry);if(socket){socket.onclose=null;socket.close();socket=null;}sessionStorage.removeItem('room');room=null;show('game',false);show('home',true);notice('');history.replaceState(null,'',location.pathname);};
for(const a of ['start','buzz','correct','wrong','skip','next'])$(a).onclick=guard(()=>command(a));
$('buzz').onclick=guard(async()=>{await command('buzz');$('chat-text').focus();$('chat').scrollIntoView({behavior:'smooth',block:'nearest'});});
$('finish').onclick=guard(async()=>{if(confirm('Завершить игру и показать итоговый счёт?'))await command('finish');});
$('board').onclick=guard(async e=>{const b=e.target.closest('[data-question]');if(b&&!b.disabled)await command('select',b.dataset.question);});
$('invite').onclick=guard(async()=>{const link=config.bot_username?`https://t.me/${config.bot_username}?start=${room.code}`:`${location.origin}/?room=${room.code}`;if(tg?.initData&&config.bot_username)tg.openTelegramLink(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent('Крысиные бега! Код: '+room.code)}`);else if(navigator.clipboard){await navigator.clipboard.writeText(link);notice('Ссылка скопирована. Код: '+room.code);}else notice('Код комнаты: '+room.code);});
window.addEventListener('online',()=>{if(room)connect(room.code);});document.addEventListener('visibilitychange',()=>{if(!document.hidden&&room)connect(room.code);});
guard(async()=>{tg?.ready();tg?.expand();config=await api('/config');try{auth=JSON.parse(sessionStorage.getItem('auth'));}catch{auth=null;}if(auth){try{auth.user=await api('/me');}catch{auth=null;sessionStorage.removeItem('auth');}}if(!auth&&tg?.initData)auth=await api('/login',{init_data:tg.initData});if(auth)await entered();else if(config.dev_mode)show('login',true);else notice('Откройте игру через Telegram-бота.');})();
