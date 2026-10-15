const questionDefaults={time_limit:45,points:100};
function defaultQuestionValue(key) {return state.doc?.settings?.[key]??questionDefaults[key];}
function questionValue(q,key) {return q[key]??defaultQuestionValue(key);}
function renderGameSettings() {
  for(const [key,id] of [['time_limit','game-time-limit'],['points','game-points']]){
    $(id).value=defaultQuestionValue(key);$(id).disabled=state.busy;
  }
  $('reset-question-times').disabled=state.busy||!state.doc?.rounds.some(q=>q.type==='question'&&'time_limit' in q);
}
function renderQuestionDefaults() {
  for(const [key,id] of [['time_limit','time-limit'],['points','points']]){
    $(id).placeholder='Из игры: '+defaultQuestionValue(key);
  }
}
function initGameSettings() {
  for(const [key,id] of [['time_limit','game-time-limit'],['points','game-points']]){
    $(id).oninput=()=>{
      if(!state.doc||state.busy)return;
      if(!state.doc.settings||typeof state.doc.settings!=='object'||Array.isArray(state.doc.settings))state.doc.settings={};
      state.doc.settings[key]=$(id).value.trim()===''?'':Number($(id).value);
      markDirty();renderQuestionDefaults();renderPreview();
    };
  }
  $('reset-question-times').onclick=()=>{
    if(!state.doc||state.busy)return;
    const questions=state.doc.rounds.filter(q=>q.type==='question'&&'time_limit' in q);
    if(!questions.length||!confirm(`Использовать общее время игры для всех вопросов? Свои значения времени будут сброшены у ${countLabel(questions.length,['вопроса','вопросов','вопросов'])}.`))return;
    for(const q of questions)delete q.time_limit;
    markDirty();renderRound();notice('Все вопросы используют общее время игры.');
  };
}
