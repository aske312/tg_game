const editorNav={gameTab:'rounds',stageTab:'questions',filter:null,search:'',libraryOpen:false};
function resetStageNavigation() {
  pauseClipEditor();
  editorNav.stageTab='questions';editorNav.filter=null;editorNav.search='';
  $('question-search').value='';$('add-stage-panel').open=false;
}
function resetEditorNavigation() {resetStageNavigation();editorNav.gameTab='rounds';setLibraryOpen(false);}
function setLibraryOpen(open) {
  editorNav.libraryOpen=open;$('studio').classList.toggle('library-open',open);
  $('toggle-games').setAttribute('aria-expanded',String(open));
  show('library-backdrop',open&&window.matchMedia('(max-width:1199px)').matches);
}
function selectGameTab(name) {if(state.busy)return;editorNav.gameTab=name;renderEditorNavigation();}
function selectStageTab(name) {if(state.busy)return;editorNav.stageTab=name;editorNav.gameTab='rounds';renderEditorNavigation();}
function visibleStageItems() {
  return stageQuestions().filter(({q})=>{
    const filter=editorNav.filter;
    if(stage()?.type==='grid'&&filter){const key=categoryKey(q.category);if(filter.kind==='missing'?gridCategories().some(name=>categoryKey(name)===key):key!==filter.name)return false;}
    return !editorNav.search||String(q.type==='event'?q.title:q.text).toLocaleLowerCase('ru').includes(editorNav.search);
  });
}
function applyQuestionFilter() {
  const visible=visibleStageItems();if(!visible.some(({i})=>i===state.index))state.index=visible[0]?.i??-1;
  renderRounds();renderRound();updateActions();
}
function openCategoryQuestions(name) {
  if(state.busy)return;
  editorNav.filter=categoryKey(name)?{kind:'category',name:categoryKey(name)}:{kind:'missing'};
  editorNav.search='';$('question-search').value='';editorNav.gameTab='rounds';editorNav.stageTab='questions';
  applyQuestionFilter();renderEditorNavigation();
}
function renderQuestionFilter() {
  const grid=stage()?.type==='grid';show('question-category-filter-field',grid);
  if(!grid)return;
  const names=gridCategories();
  const chosen=editorNav.filter?.kind==='missing'?'missing':editorNav.filter?'cat:'+editorNav.filter.name:'';
  $('question-category-filter').innerHTML='<option value="">Все категории</option>'+names.filter(categoryKey).map(name=>`<option value="${esc('cat:'+categoryKey(name))}">${esc(name)} · ${stageQuestions().filter(({q})=>categoryKey(q.category)===categoryKey(name)).length}</option>`).join('')+'<option value="missing">Без категории</option>';
  if([...$('question-category-filter').options].some(o=>o.value===chosen))$('question-category-filter').value=chosen;
  else editorNav.filter=null;
}
function renderEditorNavigation() {
  if(!state.doc)return;
  const s=stage(),grid=s?.type==='grid';
  if(!grid&&editorNav.stageTab==='categories')editorNav.stageTab='questions';
  if(editorNav.gameTab!=='rounds'||editorNav.stageTab!=='questions')pauseClipEditor();
  show('stage-tab-categories',grid);
  for(const button of $('game-tabs').querySelectorAll('[data-game-tab]')){const active=button.dataset.gameTab===editorNav.gameTab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;button.disabled=state.busy;}
  for(const tab of ['rounds','info','files'])show('game-'+tab+'-pane',editorNav.gameTab===tab);
  for(const button of $('stage-tabs').querySelectorAll('[data-stage-tab]')){const active=button.dataset.stageTab===editorNav.stageTab;button.setAttribute('aria-selected',String(active));button.tabIndex=active?0:-1;button.disabled=state.busy;}
  for(const tab of ['questions','categories','settings'])show('stage-'+tab+'-pane',!!s&&editorNav.stageTab===tab&&(tab!=='categories'||grid));
  show('no-stages',!s);show('stage-tabs',!!s);show('stage-delete',!!s);
  $('editor-location').textContent=editorNav.gameTab==='rounds'?(s?' / Раунд '+(state.stageIndex+1):' / Раунды'):' / '+(editorNav.gameTab==='info'?'Настройки игры':'Файлы');
  $('active-stage-title').textContent=s?.title||(s?'Без названия':'Добавь первый раунд');$('active-stage-mode').textContent=s?`Раунд ${state.stageIndex+1} · ${modeTitles[s.type]||''}`:'';
  const items=stageQuestions(),questions=items.filter(({q})=>q.type==='question').length,events=items.length-questions;
  $('active-stage-count').textContent=s?countLabel(questions,['вопрос','вопроса','вопросов'])+(events?' · '+countLabel(events,['событие','события','событий']):''):'';
  show('add-event',!grid);
  $('visible-question-count').textContent=String(visibleStageItems().length);
  $('no-rounds').textContent=editorNav.search?'Ничего не найдено. Измени поиск.':editorNav.filter?'В этой категории пока нет вопросов. Добавь первый.':'Добавь первый вопрос этого раунда.';
  renderQuestionFilter();
}
function initEditorNavigation() {
  $('game-tabs').onclick=e=>{const b=e.target.closest('[data-game-tab]');if(b)selectGameTab(b.dataset.gameTab);};
  $('stage-tabs').onclick=e=>{const b=e.target.closest('[data-stage-tab]');if(b)selectStageTab(b.dataset.stageTab);};
  for(const id of ['game-tabs','stage-tabs'])$(id).onkeydown=e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
    const tabs=[...$(id).querySelectorAll('[role=tab]')].filter(b=>!b.hidden&&!b.disabled),index=tabs.indexOf(document.activeElement);if(index<0)return;
    e.preventDefault();const target=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[target].click();tabs[target].focus();
  };
  $('open-categories').onclick=()=>selectStageTab('categories');
  $('question-search').oninput=()=>{editorNav.search=$('question-search').value.trim().toLocaleLowerCase('ru');applyQuestionFilter();};
  $('question-category-filter').onchange=()=>{const value=$('question-category-filter').value;editorNav.filter=value==='missing'?{kind:'missing'}:value?{kind:'category',name:value.slice(4)}:null;applyQuestionFilter();};
  $('toggle-games').onclick=()=>setLibraryOpen(!editorNav.libraryOpen);
  $('empty-browse').onclick=()=>setLibraryOpen(true);$('library-backdrop').onclick=()=>setLibraryOpen(false);
  window.addEventListener('keydown',e=>{if(e.key==='Escape')setLibraryOpen(false);});
  window.addEventListener('resize',()=>setLibraryOpen(editorNav.libraryOpen));
}
