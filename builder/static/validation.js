const publicationValidation={checked:false,issues:[],serial:0,timer:null};
const publicationFields={text:'question-text',answer:'answer',points:'points',time_limit:'time-limit',accepted_answers:'accepted-answers','choices.0':'choice-a','choices.1':'choice-b',correct_choice:'correct-choice',category:'grid-category','effect.type':'effect-type','effect.target':'effect-target','effect.questions':'effect-duration','effect.value':'effect-value','media.type':'media-type','media.audio_only':'video-audio-only','media.file':'media-file','media.start':'clip-start','media.end':'clip-end'};

function resetPublicationValidation() {
  clearTimeout(publicationValidation.timer);publicationValidation.serial++;
  publicationValidation.checked=false;publicationValidation.issues=[];renderPublicationValidation();
}
function issueStage(issue) {
  return issue.stage_id!=null?state.doc?.stages.findIndex(s=>s.id===issue.stage_id):issue.stage_index;
}
function issueItem(issue) {
  return issue.item_id!=null?state.doc?.rounds.findIndex(q=>q.id===issue.item_id):issue.item_index;
}
function issueField(issue) {
  const item=issueItem(issue),si=issueStage(issue);
  if(si==null)return 'game-title';
  if(item==null)return {answer_mode:'stage-answer-mode',title:'stage-title',categories:'new-category',questions:'add-question'}[issue.field];
  if(issue.field==='title')return 'event-title';
  if(issue.field==='text'&&state.doc?.rounds[item]?.type==='event')return 'event-text';
  return publicationFields[issue.field];
}
function renderPublicationValidation() {
  for(const node of document.querySelectorAll('[data-publication-invalid]')){
    node.removeAttribute('aria-invalid');
    const described=(node.getAttribute('aria-describedby')||'').split(' ').filter(id=>!id.startsWith('publication-field-')).join(' ');
    if(described)node.setAttribute('aria-describedby',described);else node.removeAttribute('aria-describedby');
    delete node.dataset.publicationInvalid;
  }
  for(const node of document.querySelectorAll('[data-publication-message]'))node.remove();
  const issues=publicationValidation.issues;
  show('publication-errors',issues.length>0);
  $('publication-error-count').textContent=`Нужно исправить: ${issues.length}`;
  $('publication-error-list').innerHTML=issues.map((issue,i)=>`<li><button type="button" data-publication-issue="${i}"><strong>${esc(issue.location)}</strong><span>${esc(issue.message)}</span><span class="issue-link">Открыть поле →</span></button></li>`).join('');
  for(const button of $('stage-list').querySelectorAll('[data-stage]'))button.classList.toggle('has-errors',issues.some(issue=>issueStage(issue)===Number(button.dataset.stage)));
  for(const button of $('round-list').querySelectorAll('[data-round]'))button.classList.toggle('has-errors',issues.some(issue=>issueItem(issue)===Number(button.dataset.round)));
  const grouped=new Map();
  for(const issue of issues){
    const si=issueStage(issue),qi=issueItem(issue);
    if(si!=null&&si!==state.stageIndex)continue;
    if(qi!=null&&qi!==state.index)continue;
    const id=issueField(issue);if(!id||!$(id))continue;
    if(!grouped.has(id))grouped.set(id,[]);grouped.get(id).push(issue.message);
  }
  for(const [id,messages] of grouped){
    const field=$(id),message=document.createElement('p');
    message.id='publication-field-'+id;message.className='field-error';message.dataset.publicationMessage='1';message.textContent=messages.join(' ');
    field.setAttribute('aria-invalid','true');field.dataset.publicationInvalid='1';
    field.setAttribute('aria-describedby',((field.getAttribute('aria-describedby')||'')+' '+message.id).trim());
    field.insertAdjacentElement('afterend',message);
  }
}
function openPublicationIssue(issue) {
  if(!issue||!state.doc)return;
  pauseClipEditor();
  const si=issueStage(issue),qi=issueItem(issue);
  if(si==null)editorNav.gameTab='info';
  else {
    if(si<0)return;
    selectStage(si);editorNav.gameTab='rounds';
    if(qi!=null){if(qi<0)return;state.index=qi;editorNav.stageTab='questions';}
    else editorNav.stageTab=issue.field==='categories'?'categories':issue.field==='questions'?'questions':'settings';
    renderStages();renderStageSettings();renderRounds();renderRound();
  }
  renderEditorNavigation();renderPublicationValidation();
  if(issue.field.startsWith('media.'))$('material-panel').open=true;
  if(issue.field==='accepted_answers')$('answer-variants').open=true;
  const field=$(issueField(issue));
  setTimeout(()=>{field?.scrollIntoView({block:'center',behavior:'smooth'});field?.focus({preventScroll:true});},0);
}
function setPublicationIssues(issues,navigate=false) {
  publicationValidation.checked=true;publicationValidation.issues=issues;
  renderPublicationValidation();if(navigate&&issues.length)openPublicationIssue(issues[0]);
}
async function validatePublication(navigate=false) {
  const serial=++publicationValidation.serial,game=state.snapshot.id;
  const result=await api('/games/'+id()+'/validate','POST',{document:state.doc,revision:state.snapshot.revision});
  if(serial!==publicationValidation.serial||game!==state.snapshot?.id)return false;
  const issues=result.issues;
  // Browser metadata also catches clip bounds beyond the actual recording length.
  for(const [index,q] of state.doc.rounds.entries()){
    if(q.type!=='question'||!q.media||!['audio','video'].includes(q.media.type)||issues.some(i=>i.item_index===index&&i.field.startsWith('media.')))continue;
    const problem=clipProblem(q.media,clipEditor.durations.get(clipDurationKey(q.media))??null);
    if(!problem)continue;
    const si=state.doc.stages.findIndex(s=>s.id===q.stage),s=state.doc.stages[si];
    const position=state.doc.rounds.slice(0,index+1).filter(item=>item.stage===q.stage).length;
    issues.push({stage_index:si,stage_id:s.id,item_index:index,item_id:q.id,field:'media.end',location:`Раунд ${si+1} «${s.title}» → Вопрос ${position}`,message:problem});
  }
  setPublicationIssues(issues,navigate);
  return issues.length===0;
}
function schedulePublicationValidation() {
  if(!publicationValidation.checked)return;
  clearTimeout(publicationValidation.timer);publicationValidation.serial++;
  publicationValidation.timer=setTimeout(()=>{if(!state.busy)validatePublication().catch(()=>{});},400);
}
