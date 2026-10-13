const eventOptions={
  double_reward:{title:'Двойная награда',positive:true,reward:2},
  shield:{title:'Защита от штрафа',positive:true,penalty:0},
  reward_multiplier:{title:'Множитель награды',positive:true,param:'factor',initial:2},
  bonus_points:{title:'Дополнительные очки за верный ответ',positive:true,param:'amount',initial:100},
  random_buff:{title:'Случайный положительный эффект',positive:true},
  half_reward:{title:'Половина награды',positive:false,reward:.5},
  double_penalty:{title:'Двойной штраф',positive:false,penalty:2},
  reward_reduction:{title:'Уменьшение награды',positive:false,param:'factor',initial:.5},
  penalty_multiplier:{title:'Множитель штрафа',positive:false,param:'factor',initial:2},
  penalty_points:{title:'Дополнительный штраф за ошибку',positive:false,param:'amount',initial:100},
  random_debuff:{title:'Случайный отрицательный эффект',positive:false}
};
function eventOption(effect=round()?.effect) {return eventOptions[effect?.type];}
function eventDescription(effect) {
  const option=eventOption(effect);if(!option)return 'Выбери эффект события.';
  if(effect.type==='random_buff')return 'Случайно выбирается двойная награда или защита от штрафа.';
  if(effect.type==='random_debuff')return 'Случайно выбирается половина награды или двойной штраф.';
  const factor=Number(effect.factor??option.initial),amount=Number(effect.amount??option.initial);
  let reward=option.reward??1,penalty=option.penalty??1,bonus=0,extra=0;
  if(['reward_multiplier','reward_reduction'].includes(effect.type))reward=factor;
  if(effect.type==='penalty_multiplier')penalty=factor;
  if(effect.type==='bonus_points')bonus=amount;
  if(effect.type==='penalty_points')extra=amount;
  return `При стоимости вопроса 100 очков: за верный ответ +${Math.trunc(100*reward)+bonus}, за ошибку −${Math.trunc(100*penalty)+extra}.`;
}
function renderEffect() {
  const effect=round()?.effect;if(!effect)return;
  const option=eventOption(effect),positive=option?.positive??true;
  $('effect-polarity').value=positive?'positive':'negative';
  $('effect-type').innerHTML=Object.entries(eventOptions).filter(([,o])=>o.positive===positive).map(([key,o])=>`<option value="${key}">${esc(o.title)}</option>`).join('');
  if(!option){const invalid=new Option('Неизвестный эффект: '+effect.type,effect.type);invalid.disabled=true;$('effect-type').append(invalid);}
  $('effect-type').value=effect.type;
  const param=option?.param,percent=effect.type==='reward_reduction';
  show('effect-param-field',!!param);
  $('effect-param-label').textContent=param==='amount'?(positive?'Бонус за верный ответ, очков':'Штраф за ошибку, очков'):percent?'Доля награды, %':'Множитель';
  $('effect-value').min=percent?'0':'1';$('effect-value').step=param==='amount'?'1':percent?'1':'0.01';
  if(percent)$('effect-value').max='100';else $('effect-value').removeAttribute('max');
  if(param&&document.activeElement!==$('effect-value'))$('effect-value').value=(effect[param]??option.initial)*(percent?100:1);
  $('effect-param-hint').textContent=percent?'Например, 25% оставит четверть обычной награды.':param==='amount'?(positive?'Добавляется к обычной награде за каждый верный ответ.':'Добавляется к обычному штрафу за каждую ошибку.'):'Например, 3 увеличит награду или штраф втрое.';
  $('effect-explanation').textContent=eventDescription(effect)+' Новое событие заменяет предыдущий эффект у своих получателей. Длительность считается в вопросах, включая следующие раунды.';
}
function changeEventType(type) {
  if(state.busy||round()?.type!=='event')return;
  const effect=round().effect,option=eventOptions[type];if(!option)return;
  effect.type=type;delete effect.factor;delete effect.amount;
  if(option.param)effect[option.param]=option.initial;
  markDirty();renderEffect();renderPreview();
}
function initEvents() {
  $('effect-polarity').onchange=()=>changeEventType($('effect-polarity').value==='positive'?'double_reward':'double_penalty');
  $('effect-type').onchange=()=>changeEventType($('effect-type').value);
  $('effect-value').oninput=()=>{
    if(state.busy||round()?.type!=='event')return;
    const option=eventOption();if(!option?.param)return;
    round().effect[option.param]=Number($('effect-value').value)/(round().effect.type==='reward_reduction'?100:1);
    markDirty();renderEffect();renderPreview();
  };
}
