// Keep the player's primary action inside the visible viewport, including keyboards.
const mobileLayout={pending:false,baselineWidth:0,baselineHeight:0};
function updateMobileClient(){
  if(mobileLayout.pending)return;
  mobileLayout.pending=true;
  requestAnimationFrame(()=>{
    mobileLayout.pending=false;
    const body=document.body,root=document.documentElement,viewport=window.visualViewport;
    const mobile=window.matchMedia('(max-width:760px), (max-height:500px) and (pointer:coarse)').matches;
    const focused=document.activeElement,editing=!!focused&&['INPUT','TEXTAREA','SELECT'].includes(focused.tagName);
    const zoomed=viewport&&Math.abs(viewport.scale-1)>.05;
    if(!editing||Math.abs(innerWidth-mobileLayout.baselineWidth)>80){
      mobileLayout.baselineWidth=innerWidth;mobileLayout.baselineHeight=innerHeight;
    }
    const inset=mobile&&editing&&viewport&&!zoomed?Math.max(0,innerHeight-viewport.height-viewport.offsetTop):0;
    const keyboard=mobile&&editing&&!zoomed&&(inset>80||innerHeight<mobileLayout.baselineHeight*.75);
    body.dataset.mobileKeyboardOpen=String(!!keyboard);
    root.style.setProperty('--keyboard-inset',inset+'px');
    let mode='none',dock=null;
    const player=typeof room!=='undefined'&&room&&!isDisplay()&&!isHost();
    const active=mobile&&!zoomed&&player&&!room.paused&&!room.scores_visible&&!$('question').hidden;
    if(active&&['question','review'].includes(room.phase)&&!$('my-answer').hidden){mode='sent';dock=$('my-answer');}
    else if(active&&room.phase==='question'){
      if(!$('timeout-hint').hidden){mode='expired';dock=$('timeout-hint');}
      else if(room.can_buzz&&!$('buzz-answer').hidden&&!$('buzz-answer').disabled){mode='buzz';dock=$('buzz-answer');}
      else if(canAnswer()&&!$('answer-send').disabled){
        if(!$('answer-form').hidden){mode='text';dock=$('answer-form');}
        else if(!$('binary-options').hidden){mode='binary';dock=$('binary-options');}
      }
    }
    body.dataset.mobileAnswer=mode;
    body.dataset.mobileTimer=String(!!$('timer').textContent);
    if(mobile&&focused===$('answer-text')&&($('answer-form').hidden||$('answer-send').disabled))focused.blur();
    const height=dock?Math.ceil(dock.getBoundingClientRect().height):0;
    root.style.setProperty('--answer-dock-height',height+'px');
  });
}
window.addEventListener('resize',updateMobileClient);
window.addEventListener('orientationchange',updateMobileClient);
window.visualViewport?.addEventListener('resize',updateMobileClient);
window.visualViewport?.addEventListener('scroll',updateMobileClient);
document.addEventListener('focusin',updateMobileClient);
document.addEventListener('focusout',updateMobileClient);
if(typeof ResizeObserver!=='undefined'){
  const observer=new ResizeObserver(updateMobileClient);
  for(const id of ['answer-form','binary-options','buzz-answer','my-answer','timeout-hint'])observer.observe($(id));
}
updateMobileClient();
