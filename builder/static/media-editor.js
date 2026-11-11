function uploadEditorMedia(file,kind) {
  return new Promise((resolve,reject)=>{
    const request=new XMLHttpRequest();
    const label=$('media-upload-label'),progress=$('media-upload-progress');
    show('media-upload',true);show('media-fields',true);$('media-fields').setAttribute('aria-busy','true');
    label.textContent='Загружаем файл…';progress.removeAttribute('value');
    request.open('POST','/api/games/'+id()+'/media?kind='+encodeURIComponent(kind));
    request.setRequestHeader('X-Builder-Request','1');
    request.responseType='json';
    request.upload.onprogress=event=>{
      if(event.lengthComputable){
        const percent=Math.min(100,Math.floor(event.loaded/event.total*100));
        progress.value=percent;label.textContent=`Загружаем файл: ${percent}%`;
      }
    };
    request.upload.onload=()=>{label.textContent='Файл передан. Обрабатываем на сервере…';progress.removeAttribute('value');};
    request.onload=()=>{
      const result=request.response;
      if(request.status>=200&&request.status<300&&result?.file)resolve(result);
      else reject(new Error(typeof result?.detail==='string'?result.detail:'Не удалось загрузить материал. Попробуй ещё раз.'));
    };
    request.onerror=()=>reject(new Error('Загрузка прервана: нет связи с сервером. Попробуй ещё раз.'));
    request.onabort=()=>reject(new Error('Загрузка отменена.'));
    request.send(file);
  }).finally(()=>{show('media-upload',false);$('media-fields').removeAttribute('aria-busy');});
}

// Release decoders and pending requests before replacing a media element.
function disposeEditorMedia(container) {
  for(const player of container?.querySelectorAll('audio,video')||[]){
    player.onloadedmetadata=player.onerror=player.ontimeupdate=player.onplay=null;
    player.pause();player.removeAttribute('src');player.load();
  }
}
const clipEditor={key:'',duration:null,durations:new Map()};
function clipMedia() {const q=round();return q?.type==='question'&&['audio','video'].includes(q.media?.type)?q.media:null;}
function clipTime(value) {
  if(typeof value!=='number'||!Number.isFinite(value))return String(value??'');
  const milliseconds=Math.round(value*1000),seconds=Math.floor(milliseconds/1000),fraction=milliseconds%1000;
  const base=(seconds>=3600?Math.floor(seconds/3600)+':':'')+String(Math.floor(seconds/60)%60).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');
  return base+(fraction?'.'+String(fraction).padStart(3,'0').replace(/0+$/,''):'');
}
function parseClipTime(value) {
  const text=value.trim().replace(',','.');
  if(!/^\d+(?::\d{1,2}){0,2}(?:\.\d+)?$/.test(text))return null;
  const parts=text.split(':').map(Number);
  if(parts.length>1&&parts.slice(1).some(part=>part>=60))return null;
  const result=parts.reduce((sum,part)=>sum*60+part,0);
  return Number.isFinite(result)&&result>=0?result:null;
}
function clipProblem(media,duration=null) {
  const start=media?.start??0,end=media?.end;
  if(typeof start!=='number'||!Number.isFinite(start)||start<0)return 'Укажи начало в секундах или в формате 01:23.5.';
  if(end!=null&&(typeof end!=='number'||!Number.isFinite(end)||end<=start))return 'Конец отрывка должен быть позже начала. Пустое поле означает конец записи.';
  if(duration!=null&&(start>=duration||end!=null&&end>duration+.05))return 'Границы отрывка должны находиться внутри записи.';
  return '';
}
function clipDurationKey(media) {return state.snapshot.id+':'+media.file;}
function pauseClipEditor() {$('clip-player')?.pause();for(const player of $('preview-media')?.querySelectorAll('audio,video')||[])player.pause();updateClipActions();}
function updateClipActions() {
  const media=clipMedia();
  for(const id of ['clip-use-start','clip-use-end'])$(id).disabled=state.busy||!media?.file||clipEditor.duration==null;
  for(const id of ['clip-start-range','clip-end-range'])$(id).disabled=state.busy||clipEditor.duration==null;
  for(const button of $('clip-presets').querySelectorAll('button'))button.disabled=state.busy||!media;
}
function updateClipControls() {
  const media=clipMedia();if(!media){updateClipActions();return;}
  const start=media.start??0,end=media.end,duration=clipEditor.duration;
  if(document.activeElement!==$('clip-start'))$('clip-start').value=clipTime(start);
  if(document.activeElement!==$('clip-end'))$('clip-end').value=end==null?'':clipTime(end);
  for(const id of ['clip-start-range','clip-end-range'])$(id).max=duration??1;
  $('clip-start-range').value=Math.max(0,Math.min(duration??1,Number(start)||0));
  $('clip-end-range').value=end==null?duration??1:Math.max(0,Math.min(duration??1,Number(end)||0));
  $('clip-start-label').textContent=clipTime(start);$('clip-end-label').textContent=end==null?duration==null?'до конца':clipTime(duration):clipTime(end);
  const problem=clipProblem(media,duration);$('clip-warning').textContent=problem;show('clip-warning',!!problem);
  if(!problem&&$('notice').dataset.type==='error'&&$('notice').textContent.startsWith('Отрывок:'))notice();
  $('clip-duration').textContent=duration==null?media.file?'Загружаем длительность записи…':'Загрузи аудио или видео, чтобы выбрать отрывок.':`Запись ${clipTime(duration)} · отрывок ${problem?'не задан':clipTime((end??duration)-start)}`;
  updateClipActions();
}
function renderClipEditor() {
  const media=clipMedia(),key=media?.file?state.snapshot.id+':'+round().id+':'+media.file:'';
  if(key!==clipEditor.key){
    pauseClipEditor();clipEditor.key=key;clipEditor.duration=media?.file?clipEditor.durations.get(clipDurationKey(media))??null:null;
    disposeEditorMedia($('clip-player-slot'));$('clip-player-slot').replaceChildren();
    if(key){
      const player=document.createElement(media.type);player.id='clip-player';player.controls=true;player.preload='metadata';player.src=mediaURL(media.file);player.setAttribute('aria-label','Запись для выбора отрывка');
      if(media.type==='video')player.setAttribute('playsinline','');
      player.onloadedmetadata=()=>{
        if(clipEditor.key!==key||$('clip-player')!==player)return;
        if(Number.isFinite(player.duration)&&player.duration>0){clipEditor.duration=player.duration;clipEditor.durations.set(clipDurationKey(media),player.duration);}
        updateClipControls();
      };
      player.onerror=()=>{if(clipEditor.key===key&&$('clip-player')===player){clipEditor.duration=null;$('clip-duration').textContent='Не удалось открыть запись. Загрузи материал заново.';updateClipActions();}};
      player.ontimeupdate=()=>{
        const current=clipMedia();if($('clip-player')!==player||player.paused||!current)return;
        const end=current.end??clipEditor.duration;
        if(end!=null&&player.currentTime>=end){player.pause();}
      };
      player.onplay=()=>{
        const current=clipMedia();if(!current)return;
        if(state.busy||clipProblem(current,clipEditor.duration)){player.pause();return;}
        const start=current.start||0,end=current.end??clipEditor.duration;
        if(player.currentTime<start||end!=null&&player.currentTime>=end)player.currentTime=start;
      };
      $('clip-player-slot').append(player);
    }
  }
  updateClipControls();
}
function commitClip(start,end) {
  if(state.busy||!clipMedia())return;
  pauseClipEditor();const media=clipMedia();media.start=Math.round(start*1000)/1000;media.end=end==null?null:Math.round(end*1000)/1000;
  markDirty(false);updateClipControls();
}
function validateMediaClips() {
  for(const [index,q] of state.doc.rounds.entries()){
    if(q.type!=='question'||!q.media||!['audio','video'].includes(q.media.type))continue;
    const problem=clipProblem(q.media,clipEditor.durations.get(clipDurationKey(q.media))??null);
    if(!problem)continue;
    selectStage(Math.max(0,state.doc.stages.findIndex(s=>s.id===q.stage)));state.index=index;renderRounds();renderRound();$('material-panel').open=true;
    throw new Error('Отрывок: '+problem);
  }
}
function initMediaEditor() {
  for(const [id,key] of [['clip-start','start'],['clip-end','end']]){
    $(id).oninput=()=>{
      if(state.busy||!clipMedia())return;
      const text=$(id).value,value=parseClipTime(text);
      clipMedia()[key]=key==='end'&&!text.trim()?null:value??text;
      pauseClipEditor();markDirty(false);updateClipControls();
    };
    $(id).onchange=()=>{const media=clipMedia();if(media){$(id).value=key==='end'&&media.end==null?'':clipTime(media[key]??0);updateClipControls();}};
  }
  $('clip-start-range').oninput=()=>{
    const media=clipMedia(),duration=clipEditor.duration;if(!media||duration==null)return;
    let start=Number($('clip-start-range').value),end=media.end;
    start=Math.min(start,Math.max(0,duration-.001));
    if(end!=null&&end<=start)end=Math.min(duration,start+.1);
    commitClip(start,end);
  };
  $('clip-end-range').oninput=()=>{
    const media=clipMedia(),duration=clipEditor.duration;if(!media||duration==null)return;
    let end=Number($('clip-end-range').value),start=Number(media.start)||0;
    end=Math.max(.001,end);if(start>=end)start=Math.max(0,end-.1);
    commitClip(start,end>=duration?null:end);
  };
  $('clip-use-start').onclick=()=>{const player=$('clip-player'),media=clipMedia();if(player&&media){const start=Math.min(player.currentTime,Math.max(0,clipEditor.duration-.001));commitClip(start,media.end!=null&&media.end>start?media.end:null);}};
  $('clip-use-end').onclick=()=>{const player=$('clip-player'),media=clipMedia();if(player&&media){const end=player.currentTime;if(end<=Number(media.start||0))return notice('Перемести плеер позже начала отрывка.','error');commitClip(Number(media.start)||0,end);}};
  $('clip-presets').onclick=event=>{
    const button=event.target.closest('[data-clip-length]');if(!button||state.busy||!clipMedia())return;
    if(button.dataset.clipLength==='all')return commitClip(0,null);
    const start=Number(clipMedia().start)||0,length=Number(button.dataset.clipLength),end=start+length;
    commitClip(start,clipEditor.duration==null?end:Math.min(end,clipEditor.duration));
  };
}

function renderAttachments() {
  const files=Array.isArray(round()?.attachments)?round().attachments:[];
  $('attachment-list').innerHTML=files.map((m,i)=>`<div class="attachment" data-attachment="${i}"><span>${m?.answer?'К ответу':'К вопросу'}: ${esc(typeof m?.file==='string'?m.file.split('/').pop():'Файл не выбран')}</span><label class="quiet">Заменить<input type="file" data-replace-attachment="${i}" accept="image/*,audio/*,video/*" ${state.busy?'disabled':''}></label><button type="button" class="quiet danger-text" data-remove-attachment="${i}" ${state.busy?'disabled':''}>Убрать</button><span class="hint">Для замены можно перетащить файл в эту строку</span></div>`).join('');
}
function fileMediaType(file) {
  const ext=file.name?.split('.').pop().toLowerCase();
  if(['png','jpg','jpeg','jfif','gif','webp','avif','bmp'].includes(ext))return 'image';
  if(['mp3','wav','ogg','oga','opus','m4a','aac','flac'].includes(ext))return 'audio';
  if(['mp4','webm','mov','m4v'].includes(ext))return 'video';
  return /^(image|audio|video)\//.exec(file.type||'')?.[1]||null;
}
async function uploadFiles(files,{answer=false,replace=null,primary=false}={}) {
  files=Array.from(files||[]);if(!files.length)return;
  const q=round();if(q?.type!=='question')return;
  const attachments=Array.isArray(q.attachments)?q.attachments:[];
  if(replace!==null&&files.length!==1)throw new Error('Для замены одного вложения выбери один файл.');
  const extra=files.length-(replace!==null||!answer&&(primary||!q.media?.file)?1:0);
  if(attachments.length+Math.max(0,extra)>20)throw new Error('Можно добавить не больше 20 дополнительных файлов.');
  const types=files.map(file=>{
    if(file.size>10*1024**3)throw new Error('Каждый файл должен быть не больше 10 ГБ.');
    const type=fileMediaType(file);if(!type)throw new Error('Выбери изображение, аудио или видео.');return type;
  });
  // Capture the question before awaiting uploads; selection cannot redirect the files.
  try {
    for(const [index,file] of files.entries()){
      pauseClipEditor();
      const result=await uploadEditorMedia(file,types[index]);
      const media={type:result.type,file:result.file,start:0};
      if(answer)media.answer=true;
      if(primary&&index===0)q.media=media;
      else if(replace!==null){media.answer=q.attachments[replace]?.answer===true;q.attachments[replace]=media;}
      else if(!answer&&!q.media?.file)q.media=media;
      else {q.attachments=attachments;attachments.push(media);}
      markDirty();
    }
    notice('Файлы загружены. Нажми «Сохранить черновик», чтобы сохранить изменения.');
  } finally {renderRound();$('material-panel').open=true;}
}
function initAttachments() {
  function dropZone(node,options) {
    node.ondragover=e=>{e.preventDefault();e.stopPropagation();if(e.dataTransfer)e.dataTransfer.dropEffect=state.busy?'none':'copy';node.classList.add('drag-over');};
    node.ondragleave=()=>node.classList.remove('drag-over');
    node.ondrop=e=>{e.preventDefault();e.stopPropagation();node.classList.remove('drag-over');return guarded(()=>uploadFiles(e.dataTransfer?.files,options(e)))(e);};
  }
  for(const [zone,input,options] of [['primary-drop','media-file',{primary:true}],['question-drop','question-files',{}],['answer-drop','answer-files',{answer:true}]]){
    dropZone($(zone),()=>options);
    $(input).onchange=guarded(async()=>{const files=Array.from($(input).files||[]);try{await uploadFiles(files,options);}finally{$(input).value='';}});
  }
  dropZone($('attachment-list'),e=>{const row=e.target.closest('[data-attachment]');return row?{replace:Number(row.dataset.attachment)}:{};});
  $('attachment-list').onchange=guarded(e=>{const input=e.target.closest('[data-replace-attachment]');if(input)return uploadFiles(input.files,{replace:Number(input.dataset.replaceAttachment)});});
  $('attachment-list').onclick=e=>{const button=e.target.closest('[data-remove-attachment]');if(!button||state.busy)return;round().attachments.splice(Number(button.dataset.removeAttachment),1);markDirty();renderMediaFields();renderPreview();};
  // Prevent the browser from navigating to a dropped file outside a target.
  for(const name of ['dragover','drop'])window.addEventListener(name,e=>{if(Array.from(e.dataTransfer?.types||[]).includes('Files'))e.preventDefault();});
}

function renderAttachmentPreview(q) {
  for(const media of Array.isArray(q.attachments)?q.attachments:[]){
    if(!media||typeof media.file!=='string'||!media.file||!['image','audio','video'].includes(media.type))continue;
    const label=document.createElement('p');label.textContent=media.answer?'Материал к ответу':'Дополнительный материал к вопросу';
    const player=document.createElement(media.type==='image'?'img':media.type);player.src=mediaURL(media.file);
    if(media.type==='image')player.alt=label.textContent;else {player.controls=true;player.preload='metadata';}
    $('preview-media').append(label,player);
  }
}
