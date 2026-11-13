// Download complete files; object URLs keep playback independent of later media requests.
let mediaCache={code:null,urls:new Map(),pending:new Set(),failed:new Set(),controller:null};
function clearMediaPreload(){
  mediaCache.controller?.abort();
  for(const url of mediaCache.urls.values())URL.revokeObjectURL(url);
  mediaCache={code:null,urls:new Map(),pending:new Set(),failed:new Set(),controller:null};
  show('media-preload',false);
}
function mediaSource(url){return mediaCache.urls.get(url)||url;}
function renderMediaPreload(){
  if(!isDisplay())return;
  const total=room.media_manifest?.length||0,failed=mediaCache.failed.size,pending=mediaCache.pending.size;
  show('media-preload',total>0&&(room.phase==='lobby'||failed>0||pending>0));
  $('media-preload-status').textContent=failed?`Не загружено файлов: ${failed}. Повторите загрузку перед игрой.`:
    pending?`Подготовка медиа: ${mediaCache.urls.size} из ${total}. Дождитесь завершения загрузки.`:
    `Медиа готовы: ${mediaCache.urls.size} из ${total}. Файлы доступны на этом экране до закрытия страницы.`;
  show('media-preload-retry',failed>0&&!pending);
}
function syncMediaPreload(){
  if(!isDisplay()){if(mediaCache.code)clearMediaPreload();return;}
  if(mediaCache.code!==room.code){clearMediaPreload();mediaCache.code=room.code;}
  const cache=mediaCache;
  const urls=(room.media_manifest||[]).filter(url=>!cache.urls.has(url)&&!cache.pending.has(url)&&!cache.failed.has(url));
  for(const url of urls)cache.pending.add(url);
  renderMediaPreload();
  // Limit simultaneous downloads without skipping large recordings or fetching only metadata.
  const worker=async()=>{
    while(urls.length&&mediaCache===cache){
      const url=urls.shift();
      try{
        const response=await fetch(url,{credentials:'same-origin',signal:cache.controller.signal});
        if(!response.ok)throw new Error('Media download failed');
        const blob=await response.blob();
        if(mediaCache!==cache)return;
        cache.urls.set(url,URL.createObjectURL(blob));
      }catch(error){if(mediaCache!==cache)return;cache.failed.add(url);}
      cache.pending.delete(url);renderMediaPreload();
    }
  };
  if(urls.length&&!cache.controller)cache.controller=new AbortController();
  if(urls.length)void Promise.all([worker(),worker()]).then(()=>{
    if(mediaCache!==cache||!room?.question)return;
    // Switch the current player to its downloaded file as well.
    mediaKey='';renderQuestionMedia(room.question);syncMediaPlayback();
  });
}
// The DOM is ready when deferred scripts execute.
document.getElementById('media-preload-retry').onclick=()=>{mediaCache.failed.clear();syncMediaPreload();};
