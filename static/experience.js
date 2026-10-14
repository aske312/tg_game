let crawlKey='', ceremonyKey='', ceremonyStep=-1, ceremonyStart=0, audioContext=null;

function rankedPlayers(players,host) {
  const sorted=players.filter(p=>p.id!==host).sort((a,b)=>b.score-a.score||a.name.localeCompare(b.name));
  return sorted.map(p=>({...p,rank:sorted.findIndex(other=>other.score===p.score)+1}));
}
function resultRows(players) {
  return players.map(p=>`<div class="final-result"><span>${p.rank}</span><span class="result-name">${esc(p.name)}</span><strong>${p.score} очков</strong></div>`).join('');
}
function ceremonyPlan(players,host) {
  const ranked=rankedPlayers(players,host);
  return {ranked,lower:ranked.filter(p=>p.rank>3).reverse(),podium:[...new Set(ranked.filter(p=>p.rank<=3).map(p=>p.rank))].sort((a,b)=>b-a)};
}

function renderExperience() {
  const paused=!!room.paused,scores=!!room.scores_visible,intro=room.phase==='intro',finished=room.phase==='finished';
  show('host-toolbar',hasControls()&&!['lobby','finished'].includes(room.phase));
  show('pause-game',!paused);show('continue-game',paused);
  const roundEnd=room.stage_complete&&['reveal','event'].includes(room.phase);
  show('show-scores',roundEnd&&!scores);show('hide-scores',scores);
  show('pause-panel',paused&&!scores);show('round-scores',scores);
  show('grid-intro',intro&&!paused&&!scores);
  show('skip-intro',hasControls());show('scores-next',hasControls()&&!paused);
  $('scores-next').textContent=room.stage_number===room.stage_count?'К награждению →':'Следующий раунд →';
  show('scores-waiting',scores&&!hasControls());
  $('scores-waiting').textContent=room.stage_number===room.stage_count?'Ведущий запустит награждение.':'Следующий раунд начнётся по команде ведущего.';
  show('board-waiting',isPlayer()&&room.stage?.type==='grid'&&['board','reveal'].includes(room.phase)&&!room.stage_complete&&!room.can_pick&&!paused&&!scores);
  const chooser=room.players.find(p=>p.id===room.chooser);
  $('chooser-waiting').textContent=`${chooser?.name||'Ведущий'} выбирает тему и стоимость.`;
  if(!$('board-waiting').hidden)show('question',false);
  if(paused||scores||intro){
    for(const id of ['question','question-board','event','ready','stage-banner','board-waiting'])show(id,false);
    const media=$('media-content').querySelector('audio,video');media?.pause();
  }
  if(paused||scores||intro||finished)show('round-status',false);
  if(paused||scores||intro||finished)show('finish',false);
  if(paused)$('phase').textContent='Игра на паузе';
  else if(scores)$('phase').textContent='Счёт после раунда';
  else if(intro)$('phase').textContent='Знакомимся с темами';
  if(scores){
    $('scores-title').textContent=room.stage.title;
    $('round-results').innerHTML=resultRows(rankedPlayers(room.players,room.host));
  }
  if(intro){
    const key=room.code+':'+room.stage.id;
    if(crawlKey!==key){
      crawlKey=key;
      const categories=room.stage.categories||[...new Set(room.board.map(q=>q.category))];
      $('theme-crawl').innerHTML=`<span class="eyebrow">РАУНД ${room.stage_number}</span><h2>${esc(room.stage.title)}</h2><p class="crawl-opening">Темы этого забега</p>`+categories.map((c,i)=>`<p class="crawl-category"><small>${String(i+1).padStart(2,'0')}</small>${esc(c)}</p>`).join('')+'<p class="crawl-ending">Да пребудет с кланом сыр.</p>';
    }
    const elapsed=Math.max(0,(room.paused?room.paused_at:Date.now()/1000+offset/1000)-room.intro_started_at);
    $('theme-crawl').style.animationDuration=(room.intro_until-room.intro_started_at)+'s';
    $('theme-crawl').style.animationDelay=-elapsed+'s';
    $('theme-crawl').style.animationPlayState=paused?'paused':'running';
  }
  if(finished&&ceremonyKey!==room.code){
    ceremonyKey=room.code;ceremonyStep=-1;ceremonyStart=room.finished_at||Date.now()/1000+offset/1000;
    $('award-spotlight').replaceChildren();$('final-results').replaceChildren();
  }
  if(!finished){ceremonyKey='';ceremonyStep=-1;$('confetti-layer').replaceChildren();}
  tickExperience();
}

function tickExperience() {
  if(!room)return;
  if(room.phase==='intro'){
    const now=room.paused?room.paused_at:Date.now()/1000+offset/1000;
    $('intro-countdown').textContent=Math.max(0,Math.ceil(room.intro_until-now))+' сек.';
  }
  if(room.phase!=='finished')return;
  const plan=ceremonyPlan(room.players,room.host),elapsed=Math.max(0,Date.now()/1000+offset/1000-ceremonyStart);
  const step=elapsed<3?0:Math.min(plan.podium.length+1,1+Math.floor((elapsed-3)/4));
  if(step===ceremonyStep)return;
  const previous=ceremonyStep;ceremonyStep=step;
  const complete=step>plan.podium.length;
  const revealed=plan.podium.slice(0,step);
  $('final-results').innerHTML=resultRows(complete?plan.ranked:[...plan.lower,...plan.ranked.filter(p=>revealed.includes(p.rank))]);
  show('final-results',true);show('another',complete&&!isDisplay());
  $('awards-title').textContent=complete?'Вот это был забег!':'Итоги игры';
  const rank=step>0?plan.podium[Math.min(step-1,plan.podium.length-1)]:null;
  $('awards-caption').textContent=complete?'Весь клан на финише. Спасибо за игру!':rank?`${rank} место · встречаем!`:plan.lower.length?'Начинаем с последних мест…':'Сейчас узнаем победителей…';
  $('award-spotlight').innerHTML=rank?`<span class="award-medal" aria-hidden="true">${{1:'🥇',2:'🥈',3:'🥉'}[rank]}</span><span class="eyebrow">${rank===1?'ПОБЕДИТЕЛИ КЛАНА':rank+' МЕСТО'}</span>`+plan.ranked.filter(p=>p.rank===rank).map(p=>`<h3>${esc(p.name)}</h3><p>${p.score} очков</p>`).join(''):'';
  // Do not replay an old celebration when reconnecting late.
  if(rank&&!complete&&elapsed<3+step*4-2&&(previous>=0||elapsed<4)){
    fanfare(rank);confetti(rank===1?90:40);
  }
}

async function unlockSound() {
  const Audio=window.AudioContext||window.webkitAudioContext;
  if(!Audio)return false;
  try{
    audioContext??=new Audio();
    await audioContext.resume();
    if(audioContext.state!=='running')return false;
    if(document.getElementById('enable-sound'))show('enable-sound',false);
    return true;
  }catch{return false;}
}
function fanfare(rank=1) {
  if(!audioContext||audioContext.state!=='running')return;
  const notes=rank===1?[523.25,659.25,783.99,1046.5,783.99,1046.5]:rank===2?[392,493.88,587.33,783.99]:[349.23,440,523.25,698.46];
  const now=audioContext.currentTime;
  for(const [i,frequency] of notes.entries()){
    const oscillator=audioContext.createOscillator(),gain=audioContext.createGain();
    oscillator.type='triangle';oscillator.frequency.value=frequency;
    const start=now+i*.17,end=start+(i===notes.length-1 ? .65 : .22);
    gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(.14,start+.02);gain.gain.exponentialRampToValueAtTime(.001,end);
    oscillator.connect(gain);gain.connect(audioContext.destination);oscillator.start(start);oscillator.stop(end+.02);
    oscillator.onended=()=>{oscillator.disconnect();gain.disconnect();};
  }
}
function confetti(count) {
  if(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)return;
  const layer=$('confetti-layer');layer.replaceChildren();
  for(let i=0;i<count;i++){
    const piece=document.createElement('i');
    piece.style.left=Math.random()*100+'%';piece.style.background=['#d9b85f','#8fb69a','#e2ebe4','#c29b91'][i%4];
    piece.style.animationDelay=Math.random()*.6+'s';piece.style.animationDuration=2+Math.random()*2+'s';piece.style.setProperty('--drift',(Math.random()-.5)*240+'px');
    layer.append(piece);setTimeout(()=>piece.remove(),5000);
  }
}
function resetExperience() {
  crawlKey='';ceremonyKey='';ceremonyStep=-1;$('confetti-layer').replaceChildren();
}
document.addEventListener('pointerdown',()=>{if(!audioContext||audioContext.state!=='running')void unlockSound();});
document.addEventListener('keydown',()=>{if(!audioContext||audioContext.state!=='running')void unlockSound();});
