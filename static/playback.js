let activeClip=null, displaySoundEnabled=false;

function renderDisplaySound() {
  show('display-media-unlock',isDisplay()&&!displaySoundEnabled);
}
async function sendMediaAction(action,position,duration) {
  if(!room?.question)return;
  const body={action,question:room.question.id,media_mode:mediaTransport().mode||'excerpt'};
  if(position!==undefined)body.position=position;
  if(duration!==undefined)body.duration=duration;
  apply(await api(isDisplay()?'/display/media':'/rooms/'+room.code+'/action',body));
}
function mediaTransport() {
  return room?.media_playback&&room.media_playback.question===room?.question?.id?room.media_playback:
    {question:room?.question?.id,playing:room?.phase==='question',position:0,updated_at:0,revision:0};
}
function syncMediaPlayback() {
  if(!activeClip?.ready||!isDisplay())return;
  activeClip.sync();
}
function renderHostMediaToggle() {
  const button=$('display-media-toggle'),playing=mediaTransport().playing;
  button.disabled=!!room?.paused||!!room?.scores_visible||['board','scores'].includes(room?.display_scene);
  button.textContent=playing?'Ⅱ Пауза':'▶ Воспроизвести';
  button.setAttribute('aria-label',playing?'Поставить запись на паузу на демонстрации':'Воспроизвести запись на демонстрации');
}
function renderQuestionMedia(q) {
  const m=q?.media,av=['audio','video'].includes(m?.kind),host=isHost()&&av&&room.phase!=='finished';
  show('host-media-controls',host);
  renderHostMediaToggle();
  const visible=!!m&&(!av||isDisplay());
  show('media-content',visible);
  const full=mediaTransport().mode==='full';
  const key=room.code+':'+q?.id+':'+(isDisplay()?'display':isHost()?'host':'player')+':'+full+':'+JSON.stringify(m);
  if(key===mediaKey)return;
  mediaKey=key;
  const previous=activeClip;activeClip=null;previous?.node.pause();
  $('media-content').replaceChildren();$('media-caption').textContent='';
  if(!visible)return;
  const node=document.createElement(m.kind==='image'?'img':m.kind);
  node.onerror=()=>notice('Не удалось открыть материал. Проверьте формат файла или обновите игру.','error');
  if(m.kind==='image'){node.alt='Материал к вопросу';node.src=m.url;$('media-content').append(node);return;}
  node.preload='auto';node.controls=false;
  if(m.kind==='video')node.setAttribute('playsinline','');
  $('media-content').append(clipPlayer(node,full?{...m,start:0,end:null,full:true}:m,q.id));
  node.src=m.url;
}
function clipPlayer(node,m,questionId) {
  const wrapper=document.createElement('div');wrapper.className='clip-player';
  const controls=document.createElement('div');controls.className='clip-buttons';
  const toggle=document.createElement('button');toggle.type='button';toggle.className='secondary small';toggle.disabled=true;toggle.textContent='▶ Воспроизвести';controls.append(toggle);
  const seek=document.createElement('input');seek.type='range';seek.min=0;seek.max=0;seek.step=.1;seek.value=0;seek.disabled=true;seek.setAttribute('aria-label','Позиция в отрывке');
  const time=document.createElement('span');time.className='clip-time';time.textContent='Загрузка…';
  const start=Number(m.start)||0;
  let end=start,lastSync='',endReported=false;
  const current=()=>activeClip===controller&&room?.question?.id===questionId;
  const position=()=>Math.min(Math.max(0,node.currentTime-start),end-start);
  const update=()=>{
    if(!current())return;
    seek.value=position();time.textContent=`${mediaTime(position())} / ${mediaTime(end-start)}`;
    seek.setAttribute('aria-valuetext',time.textContent);
    toggle.textContent=node.paused?'▶ Воспроизвести':'Ⅱ Пауза';
    toggle.setAttribute('aria-label',node.paused?'Воспроизвести':'Пауза');
  };
  const attemptPlay=async(userInitiated=false)=>{
    try{
      await node.play();
      if(!current()){node.pause();return;}
      if(room.paused||room.scores_visible||['board','scores'].includes(room.display_scene)||(!userInitiated&&!mediaTransport().playing))node.pause();
      else {displaySoundEnabled=true;renderDisplaySound();}
    }catch(error){
      if(!current()||room.paused||!mediaTransport().playing||error.name==='AbortError')return;
      if(error.name==='NotAllowedError'){displaySoundEnabled=false;renderDisplaySound();}
      else notice('Не удалось воспроизвести запись. Нажмите «Воспроизвести» ещё раз.','error');
    }finally{update();}
  };
  const localPlay=async()=>{
    if(!current()||!controller.ready||room.paused||room.scores_visible||['board','scores'].includes(room.display_scene))return;
    if(node.currentTime<start||node.currentTime>=end-.05)node.currentTime=start;
    endReported=false;
    // play() starts inside the click handler, before awaiting the network command.
    const playing=attemptPlay(true);
    await sendMediaAction('media_play',position(),end-start);
    await playing;
  };
  const controller={node,ready:false,localPlay,sync(){
    if(!current())return;
    const state=mediaTransport(),key=JSON.stringify([state,room.paused,room.scores_visible]);
    if(lastSync===key)return;
    lastSync=key;
    const playing=state.playing&&!room.paused&&!room.scores_visible&&!['board','scores'].includes(room.display_scene)&&['question','review','reveal'].includes(room.phase);
    const elapsed=playing&&state.updated_at?Math.max(0,(Date.now()+offset)/1000-state.updated_at):0;
    const target=Math.max(0,Math.min(end-start,(state.position||0)+elapsed));
    if(Math.abs(node.currentTime-start-target)>.25)node.currentTime=start+target;
    if(playing&&target<end-start-.02){endReported=false;void attemptPlay();}
    else node.pause();
    update();
  }};
  activeClip=controller;
  toggle.onclick=guard(async()=>{
    if(!current())return;
    toggle.disabled=true;
    try{
      if(node.paused)await localPlay();
      else {node.pause();update();await sendMediaAction('media_pause',position(),end-start);}
    }finally{if(current())toggle.disabled=!controller.ready;}
  });
  const metadata=()=>{
    if(!current()||!Number.isFinite(node.duration)||controller.ready)return;
    end=Math.min(m.end==null?node.duration:Number(m.end),node.duration);
    controller.ready=end>start;toggle.disabled=seek.disabled=!controller.ready;
    if(!controller.ready){notice('Отрывок за пределами записи.','error');return;}
    seek.max=end-start;node.currentTime=start;update();
    $('media-caption').textContent=(m.full?'Полная запись':m.kind==='audio'?'Аудиоотрывок':'Видеоотрывок')+' · '+mediaTime(end-start);
    syncMediaPlayback();
  };
  node.addEventListener('loadedmetadata',metadata);node.addEventListener('durationchange',metadata);
  const finish=()=>{
    if(!current()||!controller.ready)return;
    if(node.currentTime>=end-.02){
      node.pause();if(node.currentTime>end)node.currentTime=end;
      if(!endReported&&mediaTransport().playing){endReported=true;void sendMediaAction('media_pause',end-start,end-start).catch(()=>{});}
    }
    update();
  };
  node.addEventListener('timeupdate',finish);node.addEventListener('ended',finish);
  for(const event of ['play','pause'])node.addEventListener(event,update);
  node.addEventListener('seeking',()=>{if(controller.ready&&(node.currentTime<start||node.currentTime>end))node.currentTime=Math.min(end,Math.max(start,node.currentTime));});
  seek.oninput=()=>{if(current()&&controller.ready){node.currentTime=start+Math.max(0,Math.min(end-start,Number(seek.value)));update();}};
  seek.onchange=guard(()=>current()?sendMediaAction('media_seek',position(),end-start):undefined);
  const volume=document.createElement('input');volume.type='range';volume.min=0;volume.max=1;volume.step=.05;volume.value=1;volume.setAttribute('aria-label','Громкость');volume.oninput=()=>{node.volume=Number(volume.value);};
  const label=document.createElement('label');label.className='clip-volume';label.textContent='Громкость';label.append(volume);
  node.hidden=m.kind==='audio';wrapper.append(node);wrapper.append(controls);wrapper.append(seek);wrapper.append(time);wrapper.append(label);
  return wrapper;
}
