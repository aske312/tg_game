let activeClip=null, mediaNode=null, mediaNotice='', displaySoundEnabled=false;
let additionalPlayers=[];
let mediaEndReported='';
function reportMediaEnd(){
  if(!activeClip?.ended||additionalPlayers.some(p=>!p._finished)||!mediaTransport().playing)return;
  const key=room.code+':'+room.question.id+':'+mediaTransport().revision;
  if(mediaEndReported===key)return;
  mediaEndReported=key;
  const length=Math.max(activeClip.length,...additionalPlayers.map(p=>Math.max(0,Math.min(p._media.end??p.duration,p.duration)-(p._media.start||0))));
  void sendMediaAction('media_pause',length,length).catch(()=>{mediaEndReported='';});
}
function soloMediaPractice(){return !isDisplay()&&!!room?.practice&&room.owner===auth.user.id&&room.host!==auth.user.id;}
function mediaPlaybackSurface(){return isDisplay()||soloMediaPractice();}
function additionalMediaActive(){return room&&!room.paused&&!room.scores_visible&&['question','review','reveal'].includes(room.phase)&&['question','answer'].includes(room.display_scene||'question');}

function mediaError(message){mediaNotice=message;notice(message,'error');}
function clearMediaError(){if(mediaNotice&&$('notice').textContent===mediaNotice)notice('');mediaNotice='';}

function disposeQuestionMedia(){
  activeClip=null;mediaEndReported='';
  for(const player of additionalPlayers){player.onplay=player.ontimeupdate=player.onloadedmetadata=player.onerror=player.onended=null;player.pause();player.removeAttribute('src');player.load();}
  additionalPlayers=[];
  for(const player of $('media-content').querySelectorAll('audio,video')){player.pause();player.removeAttribute('src');player.load();}
  clearMediaError();
  if(mediaNode){
    mediaNode.onerror=null;
    if(['AUDIO','VIDEO'].includes(mediaNode.tagName)){mediaNode.pause();mediaNode.removeAttribute('src');mediaNode.load();}
    else mediaNode.removeAttribute('src');
  }
  mediaNode=null;mediaKey='';$('media-content').replaceChildren();
}

function currentSceneMedia(q=room?.question){
  const answer=displayScene()==='answer';
  return [q?.media,...(q?.attachments||[])].filter(Boolean).filter(m=>{
    const answerFile=!!m.answer||(m===q?.media&&m.kind==='image'&&(m.show_in_question??!m.audio_only)===false);
    return answerFile===answer;
  });
}
function renderDisplaySound() {
  const active=['question','review','reveal'].includes(room?.phase)&&!room.paused&&!room.scores_visible&&['question','answer'].includes(room.display_scene||'question');
  $('media-unlock-description').textContent=soloMediaPractice()?'Разреши звук, затем запускай и останавливай запись кнопкой воспроизведения.':'Разрешите звук один раз. Аудио и видео запускает ведущий со своего экрана.';
  show('display-media-unlock',mediaPlaybackSurface()&&active&&!displaySoundEnabled&&currentSceneMedia().some(m=>['audio','video'].includes(m.kind)));
}
async function sendMediaAction(action,position,duration) {
  if(!room?.question)return;
  const body={action,question:room.question.id,media_mode:mediaTransport().mode||'excerpt',media_revision:mediaTransport().revision};
  if(position!==undefined)body.position=position;
  if(duration!==undefined)body.duration=duration;
  await roomRequest(isDisplay()?'/display/media':'/rooms/'+room.code+'/action',body);
}
function mediaTransport() {
  return room?.media_playback&&room.media_playback.question===room?.question?.id?room.media_playback:
    {question:room?.question?.id,playing:false,position:0,updated_at:0,revision:0};
}
function syncMediaPlayback() {
  if(mediaNode&&['AUDIO','VIDEO'].includes(mediaNode.tagName)){
    mediaNode.volume=room?.media_volume??1;
    if(!additionalMediaActive()||!mediaTransport().playing)mediaNode.pause();
  }
  for(const player of additionalPlayers){
    player.volume=room?.media_volume??1;
    const state=mediaTransport(),item=player._media,start=item.start||0;
    const elapsed=state.playing&&!room.paused?Math.max(0,(Date.now()+offset)/1000-state.updated_at):0;
    const target=start+(state.position||0)+elapsed,end=item.end??player.duration;
    if(!additionalMediaActive()||!state.playing||target>=end){player.pause();if(target>=end){player._finished=true;reportMediaEnd();}continue;}
    player._finished=false;
    if(Math.abs(player.currentTime-target)>.25)player.currentTime=target;
    if(player.paused)void player.play().catch(error=>{if(!additionalPlayers.includes(player))return;if(error.name==='NotAllowedError'){displaySoundEnabled=false;renderDisplaySound();}else if(error.name!=='AbortError')mediaError('Не удалось воспроизвести дополнительный файл.');});
  }
  if(!activeClip?.ready||!mediaPlaybackSurface())return;
  activeClip.sync();
}
function renderHostMediaToggle() {
  const button=$('display-media-toggle'),playing=mediaTransport().playing;
  button.disabled=!!room?.paused||!!room?.scores_visible||['board','scores'].includes(room?.display_scene);
  button.textContent=playing?'Ⅱ Пауза':'▶ Воспроизвести';
  button.setAttribute('aria-label',playing?'Поставить запись на паузу на демонстрации':'Воспроизвести запись на демонстрации');
}
function renderQuestionMedia(q) {
  const files=currentSceneMedia(q),m=files.find(m=>['audio','video'].includes(m.kind))||files[0];
  const av=['audio','video'].includes(m?.kind),host=hasControls()&&!!m&&room.phase!=='finished';
  show('host-media-controls',host);
  $('host-media-title').textContent=soloMediaPractice()?'Медиа в тренировке':'Медиа на демонстрации';
  $('host-media-description').textContent=soloMediaPractice()?'Запусти материал на этом устройстве, затем отправь свой ответ.':'Управление материалом на общем экране.';
  $('host-media-volume-caption').textContent=soloMediaPractice()?'Громкость':'Громкость на общем экране';
  show('display-media-toggle',host&&av);show('host-media-volume-label',host&&av);
  const volume=$('host-media-volume');
  if(document.activeElement!==volume)volume.value=Math.round((room.media_volume??1)*100);
  $('host-media-volume-value').textContent=volume.value+'%';
  const answerVisible=displayScene()==='answer';
  const hiddenPicture=(m?.show_in_question??!m?.audio_only)===false&&!answerVisible;
  const visual=files.some(item=>['image','video'].includes(item.kind)&&(answerVisible||(item.show_in_question??!item.audio_only)!==false));
  const canExpand=visual&&['question','review','reveal'].includes(room.phase)&&!room.paused&&!room.scores_visible&&['question','answer'].includes(room.display_scene||'question');
  show('display-media-expand',host&&!!visual&&!soloMediaPractice());
  $('display-media-expand').disabled=!canExpand;
  $('display-media-expand').textContent=room.media_expanded?'Свернуть медиа на общем экране':'Развернуть медиа на весь экран';
  $('display-media-expand').setAttribute('aria-pressed',String(!!room.media_expanded));
  document.body.dataset.mediaExpanded=String(isDisplay()&&!!room.media_expanded&&!!canExpand);
  renderHostMediaToggle();
  const attachments=files.filter(item=>item!==m&&!(mediaPlaybackSurface()&&item.kind==='image'&&(item.show_in_question??!item.audio_only)===false&&!answerVisible));
  const visible=attachments.some(item=>item.kind==='image'||mediaPlaybackSurface())||!!m&&(!av||mediaPlaybackSurface())&&!(mediaPlaybackSurface()&&m.kind==='image'&&hiddenPicture);
  show('media-content',visible);
  const full=mediaTransport().mode==='full';
  const key=room.code+':'+q?.id+':'+(isDisplay()?'display':isHost()?'host':'player')+':'+room.display_scene+':'+full+':'+(mediaPlaybackSurface()&&hiddenPicture)+':'+JSON.stringify([m,attachments]);
  if(key===mediaKey)return;
  disposeQuestionMedia();
  mediaKey=key;
  if(!visible)return;
  for(const item of attachments){
    if(item.kind!=='image'&&!mediaPlaybackSurface())continue;
    const hiddenVideo=item.kind==='video'&&(item.show_in_question??!item.audio_only)===false&&!answerVisible;
    const extra=document.createElement(item.kind==='image'?'img':hiddenVideo?'audio':item.kind);
    extra.src=mediaSource(item.url);
    if(item.kind==='image')extra.alt=item.answer?'Материал к ответу':'Материал к вопросу';
    else {
      additionalPlayers.push(extra);extra.volume=room.media_volume??1;
      extra.controls=false;extra.preload='auto';extra.setAttribute('playsinline','');
      const start=item.start||0;
      extra._media=item;extra.onloadedmetadata=()=>{extra.currentTime=start;syncMediaPlayback();};
      extra.onplay=()=>{if(!additionalMediaActive()){extra.pause();return;}if(extra.currentTime<start||item.end!=null&&extra.currentTime>=item.end)extra.currentTime=start;};
      extra.ontimeupdate=()=>{if(!additionalMediaActive())extra.pause();if(extra.currentTime>=Math.min(item.end??extra.duration,extra.duration)-.02){extra.pause();extra._finished=true;reportMediaEnd();}};
      extra.onended=extra.ontimeupdate;
    }
    $('media-content').append(extra);
  }
  if(!m||av&&!mediaPlaybackSurface()||mediaPlaybackSurface()&&m.kind==='image'&&hiddenPicture)return;
  const audioOnly=m.kind==='video'&&hiddenPicture;
  const node=document.createElement(m.kind==='image'?'img':m.kind);
  mediaNode=node;
  node.onerror=()=>mediaError('Не удалось открыть материал. Проверьте формат файла или обновите игру.');
  if(m.kind==='image'){node.alt='Материал к вопросу';node.src=mediaSource(m.url);$('media-content').append(node);return;}
  node.preload='auto';node.controls=false;node.volume=room.media_volume??1;
  if(m.kind==='video')node.setAttribute('playsinline','');
  const playbackMedia=m;
  $('media-content').append(clipPlayer(node,audioOnly?{...playbackMedia,kind:'audio'}:playbackMedia,q.id));
  node.src=mediaSource(m.url);
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
  const controller={node,ready:false,ended:false,length:0,localPlay,sync(){
    if(!current())return;
    node.volume=room.media_volume??1;
    const state=mediaTransport(),key=JSON.stringify([state,room.paused,room.scores_visible]);
    if(lastSync===key)return;
    lastSync=key;
    const playing=state.playing&&!room.paused&&!room.scores_visible&&!['board','scores'].includes(room.display_scene)&&['question','review','reveal'].includes(room.phase);
    const elapsed=playing&&state.updated_at?Math.max(0,(Date.now()+offset)/1000-state.updated_at):0;
    const target=Math.max(0,Math.min(end-start,(state.position||0)+elapsed));
    if(Math.abs(node.currentTime-start-target)>.25)node.currentTime=start+target;
    if(playing&&target<end-start-.02){endReported=false;controller.ended=false;void attemptPlay();}
    else node.pause();
  }};
  activeClip=controller;
  const metadata=()=>{
    if(!current()||!Number.isFinite(node.duration)||controller.ready)return;
    end=Math.min(m.end==null?node.duration:Number(m.end),node.duration);
    controller.ready=end>start;
    controller.length=end-start;
    if(!controller.ready){mediaError('Отрывок за пределами записи.');return;}
    node.currentTime=start;
    syncMediaPlayback();
  };
  node.addEventListener('loadedmetadata',metadata);node.addEventListener('durationchange',metadata);
  const finish=()=>{
    if(!current()||!controller.ready)return;
    if(node.currentTime>=end-.02){
      node.pause();if(node.currentTime>end)node.currentTime=end;
      controller.ended=true;
      if(!endReported&&mediaTransport().playing){endReported=true;reportMediaEnd();}
    }
  };
  node.addEventListener('timeupdate',finish);node.addEventListener('ended',finish);
  node.addEventListener('seeking',()=>{if(controller.ready&&(node.currentTime<start||node.currentTime>end))node.currentTime=Math.min(end,Math.max(start,node.currentTime));});
  node.hidden=m.kind==='audio';wrapper.append(node);
  return wrapper;
}
