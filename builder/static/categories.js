// Categories and counts are scoped to the selected grid round.
function categoryKey(value) {return typeof value==='string'?value.trim().toLocaleLowerCase('ru'):'';}
function normalizeStageCategories(doc) {
  for(const s of doc.stages)if(s.type==='grid'&&!('categories' in s)) {
    const names=new Map();
    for(const q of doc.rounds)if(q.stage===s.id&&categoryKey(q.category))names.set(categoryKey(q.category),q.category.trim());
    s.categories=[...names.values()];
  }
}
function gridCategories(s=stage()) {return Array.isArray(s?.categories)?s.categories:[];}
function categoryProblems(s,doc=state.doc) {
  if(s.type!=='grid')return '';
  const names=gridCategories(s),keys=names.map(categoryKey);
  if(!names.length)return 'Добавь хотя бы одну категорию сетки.';
  if(names.length>100||names.some(c=>typeof c!=='string'||!c.trim()||c.trim().length>100))return 'Названия категорий должны быть непустыми, до 100 символов.';
  if(new Set(keys).size!==keys.length)return 'Категории этого раунда должны иметь разные названия.';
  const missing=doc.rounds.filter(q=>q.stage===s.id&&q.type==='question'&&!keys.includes(categoryKey(q.category))).length;
  return missing?`Выбери категорию для ${countLabel(missing,['вопроса','вопросов','вопросов'])}.`:'';
}
function validateGridCategories() {
  for(const [index,s] of state.doc.stages.entries()){
    const problem=categoryProblems(s);if(!problem)continue;
    selectStage(index);editorNav.stageTab='categories';renderEditorNavigation();
    throw new Error(`Раунд «${s.title}»: ${problem}`);
  }
}
function categoryOverview(doc) {
  const rows=new Map();
  function entry(name) {const key=categoryKey(name);if(!rows.has(key))rows.set(key,{key,uncategorized:!key,name:key?name.trim():'Без категории',questions:0,events:0});return rows.get(key);}
  const selected=stage();
  if(selected?.type!=='grid')return [];
  for(const name of gridCategories(selected))if(categoryKey(name))entry(name);
  for(const q of doc.rounds.filter(q=>q.stage===selected.id)){const row=entry(typeof q.category==='string'?q.category:'');if(q.type==='event')row.events++;else row.questions++;}
  return [...rows.values()];
}
function renderCategoryOverview() {
  if(!state.doc)return;
  const rows=categoryOverview(state.doc);
  const hasEvents=rows.some(r=>r.events);
  for(const column of document.querySelectorAll('[data-event-column]'))column.hidden=!hasEvents;
  $('category-summary').innerHTML=rows.map(r=>`<tr data-category="${esc(r.key)}"><th scope="row"><button class="category-link" data-category-questions="${esc(r.name)}" data-category-missing="${r.uncategorized?'1':'0'}">${esc(r.name)}</button></th><td>${r.questions}</td>${hasEvents?`<td>${r.events}</td><td>${r.questions+r.events}</td>`:''}</tr>`).join('');
  const questions=rows.reduce((n,r)=>n+r.questions,0),events=rows.reduce((n,r)=>n+r.events,0);
  $('category-overview-total').textContent=countLabel(questions,['вопрос','вопроса','вопросов'])+(hasEvents?' · '+countLabel(events,['событие','события','событий']):'');
  for(const row of $('grid-category-list').querySelectorAll('.grid-category-row')){
    const name=gridCategories()[Number(row.querySelector('[data-category-name]').dataset.categoryName)];
    row.querySelector('span').textContent=countLabel(stageQuestions().filter(({q})=>q.type==='question'&&categoryKey(name)&&categoryKey(q.category)===categoryKey(name)).length,['вопрос','вопроса','вопросов']);
  }
  if(stage()?.type==='grid'){const problem=categoryProblems(stage());$('category-warning').textContent=problem;show('category-warning',!!problem);}
}
function renderCategorySelect() {
  const q=round(),grid=stage()?.type==='grid';
  show('grid-category-field',grid);
  $('grid-category').required=grid;
  if(!grid||!q)return;
  const names=gridCategories();
  $('grid-category').innerHTML='<option value="">Выбери категорию</option>'+names.filter(c=>categoryKey(c)).map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('');
  const matched=names.find(c=>categoryKey(c)&&categoryKey(c)===categoryKey(q.category));
  if(matched!==undefined)$('grid-category').value=matched;
  else if(categoryKey(q.category)){
    const option=document.createElement('option');option.value=q.category;option.textContent='Не задана в списке: '+q.category;option.disabled=true;$('grid-category').append(option);$('grid-category').value=q.category;
  }
}
function renderCategoryControls() {
  const s=stage();if(s?.type!=='grid')return;
  $('grid-category-list').innerHTML=gridCategories(s).map((name,i)=>{
    const count=stageQuestions().filter(({q})=>q.type==='question'&&categoryKey(name)&&categoryKey(q.category)===categoryKey(name)).length;
    return `<div class="grid-category-row"><input data-category-name="${i}" value="${esc(name)}" maxlength="100" aria-label="Название категории ${i+1}"><button data-category-open="${i}" class="category-count"><span>${countLabel(count,['вопрос','вопроса','вопросов'])}</span> →</button><button data-category-remove="${i}" type="button" class="icon-button danger-text" aria-label="Удалить категорию ${esc(name)}">×</button></div>`;
  }).join('');
  renderCategoryOverview();renderCategorySelect();
}
function updateCategoryActions() {
  $('add-category').disabled=state.busy||gridCategories().length>=100;
  for(const button of $('grid-category-list').querySelectorAll('button'))button.disabled=state.busy;
}
function initCategories() {
  $('add-category').onclick=()=>{
    if(state.busy||stage()?.type!=='grid')return;
    const name=$('new-category').value.trim();
    if(!name)return notice('Введи название категории.','error');
    if(gridCategories().some(c=>categoryKey(c)===categoryKey(name)))return notice('Такая категория уже есть в этом раунде.','error');
    if(gridCategories().length>=100)return;
    stage().categories.push(name);$('new-category').value='';markDirty();renderCategoryControls();updateActions();notice();
  };
  $('new-category').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('add-category').click();}};
  $('grid-category-list').oninput=e=>{if(e.target.closest('[data-category-name]')&&!state.busy){state.dirty=true;updateActions();}};
  $('grid-category-list').onchange=e=>{
    const input=e.target.closest('[data-category-name]');if(!input||state.busy)return;
    const index=Number(input.dataset.categoryName),old=stage().categories[index],name=input.value.trim();
    if(!name||gridCategories().some((c,i)=>i!==index&&categoryKey(c)===categoryKey(name))){input.value=old;notice('Укажи непустое уникальное название категории.','error');return;}
    stage().categories[index]=name;
    input.value=name;
    for(const {q} of stageQuestions())if(categoryKey(old)&&categoryKey(q.category)===categoryKey(old))q.category=name;
    if(editorNav.filter?.kind==='category'&&editorNav.filter.name===categoryKey(old))editorNav.filter.name=categoryKey(name);
    markDirty();renderCategorySelect();renderPreview();
  };
  $('grid-category-list').onclick=e=>{
    const open=e.target.closest('[data-category-open]');if(open&&!state.busy){openCategoryQuestions(gridCategories()[Number(open.dataset.categoryOpen)]);return;}
    const button=e.target.closest('[data-category-remove]');if(!button||state.busy)return;
    const index=Number(button.dataset.categoryRemove),name=stage().categories[index];
    const attached=stageQuestions().filter(({q})=>categoryKey(name)&&categoryKey(q.category)===categoryKey(name));
    if(attached.length&&!confirm(`Удалить категорию «${name}»? У ${countLabel(attached.length,['вопроса','вопросов','вопросов'])} этого раунда категория будет снята.`))return;
    for(const {q} of attached)delete q.category;
    stage().categories.splice(index,1);
    if(editorNav.filter?.kind==='category'&&editorNav.filter.name===categoryKey(name))editorNav.filter=null;
    markDirty();renderCategoryControls();renderRound();updateActions();
  };
  $('category-summary').onclick=e=>{const button=e.target.closest('[data-category-questions]');if(button)openCategoryQuestions(button.dataset.categoryMissing==='1'?'':button.dataset.categoryQuestions);};
  $('grid-category').onchange=()=>{if(!round()||state.busy)return;round().category=$('grid-category').value;if(editorNav.filter)editorNav.filter=categoryKey(round().category)?{kind:'category',name:categoryKey(round().category)}:{kind:'missing'};markDirty();renderCategoryControls();renderPreview();};
}
