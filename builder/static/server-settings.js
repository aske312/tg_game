let serverSnapshot=null,serverPoll=null,serverLoading=false,serverLaunching=false,serverGeneration=0,serverPollingStopped=false;
const serverNames={app:'Игра и бот',builder:'Конструктор'};
const serviceNames={'rat-race-web.service':'Игра','rat-race-bot.service':'Telegram-бот','rat-race-builder.service':'Конструктор','rat-race-builder-proxy.service':'HTTPS конструктора'};
function serverBytes(bytes){return Number.isFinite(bytes)?(bytes/1024**3).toLocaleString('ru-RU',{maximumFractionDigits:1})+' ГБ':'—';}
function serverVersion(version){return version?esc(version.version)+' · '+esc(version.build.slice(0,7)):'Нет сохранённой версии';}
function updateServerActions(){
  const running=serverSnapshot?.job?.status==='running';
  const disabled=!serverSnapshot?.available||running||serverLaunching||state.busy;
  $('server-update').disabled=disabled;
  const versions=Object.values(serverSnapshot?.versions||{});
  $('server-rollback').disabled=disabled||!versions.length||!versions.every(v=>v.previous&&v.current&&v.previous.build!==v.current.build);
}
function renderServerStatus(snapshot){
  serverSnapshot=snapshot;
  $('server-status-message').textContent=snapshot.available?'Состояние сервера · '+new Date().toLocaleTimeString('ru-RU'):snapshot.message;
  const m=snapshot.metrics;
  $('server-stats').innerHTML=m?[
    ['Процессор',m.cpu_percent===null?'—':m.cpu_percent+'% · '+m.cpu_count+' ядер'],
    ['Память',serverBytes(m.memory?.used)+' / '+serverBytes(m.memory?.total)],
    ['Диск',serverBytes(m.disk.used)+' / '+serverBytes(m.disk.total)],
    ['Время работы',m.uptime===null?'—':Math.floor(m.uptime/86400)+' дн. '+Math.floor(m.uptime%86400/3600)+' ч.']
  ].map(([name,value])=>`<div class="server-stat"><span>${esc(name)}</span><strong>${esc(value)}</strong></div>`).join(''):'';
  const serviceLabels={active:'Работает',inactive:'Остановлена',failed:'Ошибка',activating:'Запускается',deactivating:'Останавливается',unknown:'Недоступна'};
  $('server-services').innerHTML=Object.entries(snapshot.services||{}).map(([name,status])=>`<div class="server-service" data-status="${esc(status)}"><span>${esc(serviceNames[name]||name)}</span><strong>${esc(serviceLabels[status]||status)}</strong></div>`).join('');
  $('server-versions').innerHTML=Object.entries(snapshot.versions||{}).map(([name,v])=>`<div class="server-version"><div><strong>${esc(serverNames[name]||name)}</strong><small>Установлено: ${serverVersion(v.current)}</small></div><div><small>Для отката: ${serverVersion(v.previous)}</small></div></div>`).join('')||`<p class="hint">${esc(snapshot.version?.label||'Серверное управление не настроено')}</p>`;
  const job=snapshot.job;
  show('server-job',!!job);
  if(job){
    const titles={update:'Обновление из GitHub',rollback:'Откат версии'};
    const statuses={running:'Выполняется. Во время перезапуска связь с конструктором может пропасть.',succeeded:'Успешно завершено. Перезагрузите страницу, чтобы открыть установленную версию.',failed:'Операция завершилась с ошибкой. Проверьте журнал и установленные версии.',interrupted:'Операция прервана перезапуском службы управления. Проверьте состояние служб и версии.'};
    $('server-job-heading').textContent=titles[job.action]||'Операция';
    $('server-job-status').textContent=statuses[job.status]||job.status;
    $('server-job-log').textContent=job.log||'Подготовка операции…';
    show('server-reload',job.status==='succeeded');
  }else show('server-reload',false);
  updateServerActions();
}
function scheduleServerPoll(){
  clearTimeout(serverPoll);
  if($('app-settings-dialog').open&&!serverLaunching&&!serverPollingStopped)serverPoll=setTimeout(()=>loadServerStatus(),5000);
}
async function loadServerStatus(){
  if(serverLoading)return;
  serverLoading=true;
  const generation=serverGeneration;
  try{
    const snapshot=await api('/server');
    if(generation===serverGeneration&&$('app-settings-dialog').open)renderServerStatus(snapshot);
  }catch(error){
    if(generation!==serverGeneration)return;
    if(error.status===401){closeServerSettings();return;}
    if(error.status===404&&serverSnapshot?.job){
      $('server-status-message').textContent='Установленная версия конструктора не поддерживает эту панель. Перезагрузите страницу и проверьте версию внизу экрана.';
      show('server-reload',true);serverSnapshot=null;serverPollingStopped=true;updateServerActions();return;
    }
    if(serverSnapshot)serverSnapshot.available=false;
    updateServerActions();
    $('server-status-message').textContent=serverSnapshot?.job?.status==='running'?'Сервер перезапускается. Ожидаем восстановления связи…':error.message;
  }finally{serverLoading=false;scheduleServerPoll();}
}
function closeServerSettings(){clearTimeout(serverPoll);serverGeneration++;$('app-settings-dialog').close();}
$('app-settings').onclick=()=>{
  serverPollingStopped=false;
  $('app-settings-dialog').showModal();
  if(serverSnapshot)renderServerStatus(serverSnapshot);
  void loadServerStatus();
};
$('close-app-settings').onclick=closeServerSettings;
$('app-settings-dialog').addEventListener('close',()=>clearTimeout(serverPoll));
$('refresh-server').onclick=()=>loadServerStatus();
$('server-reload').onclick=()=>location.reload();
async function launchServerAction(action){
  if(serverLaunching||state.busy||$('server-'+action).disabled)return;
  const versions=Object.entries(serverSnapshot.versions).map(([name,v])=>serverNames[name]+': '+v.current?.version+(action==='rollback'?' → '+v.previous?.version:'')).join('\n');
  if(!confirm((action==='rollback'?'Откатить приложение на сохранённые версии?':'Установить последний опубликованный стабильный релиз GitHub?')+'\n'+versions+'\nСлужбы будут перезапущены. Выполняйте операцию между играми.'))return;
  serverLaunching=true;serverGeneration++;updateServerActions();
  try{
    if(state.dirty){
      state.busy=true;updateActions();
      try{await save();}finally{state.busy=false;updateActions();}
    }
    // Stop polling before POST so an older response cannot overwrite the new job.
    clearTimeout(serverPoll);
    const result=await api('/server/action','POST',{action});
    renderServerStatus({...serverSnapshot,job:result.job});
  }catch(error){
    notice(error.message,'error');
    $('server-status-message').textContent=error.message;
    // The server may have accepted a request before the connection was lost.
    $('server-update').disabled=$('server-rollback').disabled=true;
    await loadServerStatus();
  }finally{serverLaunching=false;updateServerActions();scheduleServerPoll();}
}
$('server-update').onclick=()=>launchServerAction('update');
$('server-rollback').onclick=()=>launchServerAction('rollback');
