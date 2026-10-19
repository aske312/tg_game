let activeClip=null, mediaNode=null, mediaNotice='', displaySoundEnabled=false;

function mediaError(message){mediaNotice=message;notice(message,'error');}
function clearMediaError(){if(mediaNotice&&$('notice').textContent===mediaNotice)notice('');mediaNotice='';}

function disposeQuestionMedia(){
  activeClip=null;
  clearMediaError();
  if(mediaNode){
    mediaNode.onerror=null;
    if(['AUDIO','VIDEO'].includes(mediaNode.tagName)){mediaNode.pause();mediaNode.removeAttribute('src');mediaNode.load();}
    else mediaNode.removeAttribute('src');
  }
  mediaNode=null;mediaKey='';$('media-content').replaceChildren();
}

function renderDisplaySound() {
  const active=['question','review','reveal'].includes(room?.phase)&&!room.paused&&!room.scores_visible&&['question','answer'].includes(room.display_scene||'question');
  show('display-media-unlock',isDisplay()&&active&&!displaySoundEnabled&&['audio','video'].includes(room?.question?.media?.kind));
}
async function sendMediaAction(action,position,duration) {
  if(!room?.question)return;
  const body={action,question:room.question.id,media_mode:mediaTransport().mode||'excerpt'};
  if(position!==undefined)body.position=position;
  if(duration!==undefined)body.duration=duration;
  await roomRequest(isDisplay()?'/display/media':'/rooms/'+room.code+'/action',body);
}
function mediaTransport() {
  return room?.media_playback&&room.media_playback.question===room?.question?.id?room.media_playback:
    {question:room?.question?.id,playing:false,position:0,updated_at:0,revision:0};
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
  const m=q?.media,av=['audio','video'].includes(m?.kind),host=isHost()&&!!m&&room.phase!=='finished';
  show('host-media-controls',host);
  show('display-media-toggle',host&&av);show('host-media-volume-label',host&&av);
  const volume=$('host-media-volume');
  if(document.activeElement!==volume)volume.value=Math.round((room.media_volume??1)*100);
  $('host-media-volume-value').textContent=volume.value+'%';
  const answerVisible=room.phase==='reveal'&&(room.display_scene||'answer')==='answer';
  const hiddenPicture=(m?.show_in_question??!m?.audio_only)===false&&!answerVisible;
  const visual=['image','video'].includes(m?.kind)&&!hiddenPicture;
  const canExpand=visual&&['question','review','reveal'].includes(room.phase)&&!room.paused&&!room.scores_visible&&['question','answer'].includes(room.display_scene||'question');
  show('display-media-expand',host&&!!visual);
  $('display-media-expand').disabled=!canExpand;
  $('display-media-expand').textContent=room.media_expanded?'Свернуть медиа на общем экране':'Развернуть медиа на весь экран';
  $('display-media-expand').setAttribute('aria-pressed',String(!!room.media_expanded));
  document.body.dataset.mediaExpanded=String(isDisplay()&&!!room.media_expanded&&!!canExpand);
  renderHostMediaToggle();
  const visible=!!m&&(!av||isDisplay())&&!(isDisplay()&&m.kind==='image'&&hiddenPicture);
  show('media-content',visible);
  const full=mediaTransport().mode==='full';
  const key=room.code+':'+q?.id+':'+(isDisplay()?'display':isHost()?'host':'player')+':'+full+':'+(isDisplay()&&hiddenPicture)+':'+JSON.stringify(m);
  if(key===mediaKey)return;
  disposeQuestionMedia();
  mediaKey=key;
  if(!visible)return;
  const audioOnly=m.kind==='video'&&hiddenPicture;
  const node=document.createElement(m.kind==='image'?'img':m.kind);
  mediaNode=node;
  node.onerror=()=>mediaError('Не удалось открыть материал. Проверьте формат файла или обновите игру.');
  if(m.kind==='image'){node.alt='Материал к вопросу';node.src=m.url;$('media-content').append(node);return;}
  node.preload='auto';node.controls=false;
  if(m.kind==='video')node.setAttribute('playsinline','');
  const playbackMedia=full?{...m,start:0,end:null,full:true}:m;
  $('media-content').append(clipPlayer(node,audioOnly?{...playbackMedia,kind:'audio'}:playbackMedia,q.id));
  node.src=m.url;
}
function clipPlayer(node,m,questionId) {
  const wrapper=document.createElement('div');wrapper.className='clip-player';
  const start=Number(m.start)||0;
  let end=start,lastSync='',endReported=false;
  const current=()=>activeClip===controller&&room?.question?.id===questionId;
  const attemptPlay=async(userInitiated=false)=>{
    try{
      await node.play();
      if(!current()){node.pause();return;}
      clearMediaError();
      if(room.paused||room.scores_visible||['board','scores'].includes(room.display_scene)||(!userInitiated&&!mediaTransport().playing))node.pause();
      else {displaySoundEnabled=true;renderDisplaySound();}
    }catch(error){
      if(!current()||room.paused||!mediaTransport().playing||error.name==='AbortError')return;
      if(error.name==='NotAllowedError'){displaySoundEnabled=false;renderDisplaySound();}
      else mediaError('Не удалось воспроизвести запись. Повторите запуск с панели ведущего.');
    }
  };
  const localPlay=async()=>{
    if(!current()||!controller.ready||!mediaTransport().playing||room.paused||room.scores_visible||['board','scores'].includes(room.display_scene))return;
    // This click grants browser sound permission; playback is requested by the host.
    await attemptPlay(true);
  };
  const controller={node,ready:false,localPlay,sync(){
    if(!current())return;
    node.volume=room.media_volume??1;
    const state=mediaTransport(),key=JSON.stringify([state,room.paused,room.scores_visible]);
    if(lastSync===key)return;
    lastSync=key;
    const playing=state.playing&&!room.paused&&!room.scores_visible&&!['board','scores'].includes(room.display_scene)&&['question','review','reveal'].includes(room.phase);
    const elapsed=playing&&state.updated_at?Math.max(0,(Date.now()+offset)/1000-state.updated_at):0;
    const target=Math.max(0,Math.min(end-start,(state.position||0)+elapsed));
    if(Math.abs(node.currentTime-start-target)>.25)node.currentTime=start+target;
    if(playing&&target<end-start-.02){endReported=false;void attemptPlay();}
    else node.pause();
  }};
  activeClip=controller;
  const metadata=()=>{
    if(!current()||!Number.isFinite(node.duration)||controller.ready)return;
    end=Math.min(m.end==null?node.duration:Number(m.end),node.duration);
    controller.ready=end>start;
    if(!controller.ready){mediaError('Отрывок за пределами записи.');return;}
    node.currentTime=start;
    syncMediaPlayback();
  };
  node.addEventListener('loadedmetadata',metadata);node.addEventListener('durationchange',metadata);
  const finish=()=>{
    if(!current()||!controller.ready)return;
    if(node.currentTime>=end-.02){
      node.pause();if(node.currentTime>end)node.currentTime=end;
      if(!endReported&&mediaTransport().playing){endReported=true;void sendMediaAction('media_pause',end-start,end-start).catch(()=>{});}
    }
  };
  node.addEventListener('timeupdate',finish);node.addEventListener('ended',finish);
  node.addEventListener('seeking',()=>{if(controller.ready&&(node.currentTime<start||node.currentTime>end))node.currentTime=Math.min(end,Math.max(start,node.currentTime));});
  node.hidden=m.kind==='audio';wrapper.append(node);
  return wrapper;
}
