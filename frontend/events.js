(() => {
  const style=document.createElement('style');
  style.textContent=`.notice-rail{position:fixed;right:14px;bottom:92px;z-index:50;display:grid;gap:7px;max-width:270px}.notice-chip{display:grid;grid-template-columns:28px 1fr 22px;gap:7px;align-items:center;padding:8px 9px;border:1px solid var(--border);border-radius:12px;background:var(--panel);box-shadow:0 8px 24px rgba(0,0,0,.12);font-size:11px}.notice-chip button{border:0;background:transparent;color:var(--muted);cursor:pointer;padding:2px}.notice-main{overflow:hidden}.notice-main strong,.notice-main small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.notice-main small{color:var(--muted);margin-top:2px}.timer-card-placeholder{display:none!important}`;
  document.head.appendChild(style);
  const rail=document.createElement('div');rail.className='notice-rail';document.body.appendChild(rail);
  const timerCards=new Map();
  const send=document.getElementById('sendButton');
  if(send){try{Object.defineProperty(send,'disabled',{configurable:true,get:()=>false,set:()=>{}})}catch(_){send.disabled=false}}

  function notice(icon,title,detail,target){const n=document.createElement('div');n.className='notice-chip';n.innerHTML=`<div>${icon}</div><div class="notice-main"><strong></strong><small></small></div><button title="Dismiss">×</button>`;n.querySelector('strong').textContent=title;n.querySelector('small').textContent=detail||'';n.querySelector('.notice-main').style.cursor=target?'pointer':'default';if(target)n.querySelector('.notice-main').onclick=()=>target.scrollIntoView({behavior:'smooth',block:'center'});n.querySelector('button').onclick=()=>n.remove();rail.appendChild(n);return n}
  window.agentieNotice=notice;

  const previousRender=window.renderCard;
  window.renderCard=function(card,message){
    if(card&&card.type==='timer'&&card.id){
      const existing=timerCards.get(String(card.id));
      if(existing&&document.body.contains(existing.wrap)){existing.update(card);const p=document.createElement('span');p.className='timer-card-placeholder';return p}
      const wrap=document.createElement('div');wrap.className='card-wrap';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);const title=document.createElement('div');title.className='card-title';el.appendChild(title);const value=document.createElement('div');value.className='card-value';el.appendChild(value);const meta=document.createElement('div');meta.className='card-meta';el.appendChild(meta);const reason=document.createElement('div');reason.className='card-meta';el.appendChild(reason);const actions=document.createElement('div');actions.className='actions';const cancel=document.createElement('button');cancel.textContent='Cancel';actions.appendChild(cancel);el.appendChild(actions);
      let current={...card},interval=null,alerted=false;const fmt=sec=>{sec=Math.max(0,Math.floor(Number(sec)||0));const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;return(h?[h,m,s]:[m,s]).map(v=>String(v).padStart(2,'0')).join(':')};
      const tick=()=>{if(current.status==='cancelled'){title.textContent='⏱ Timer';value.textContent='00:00';meta.textContent='Cancelled';el.classList.remove('timer-finished');if(interval)clearInterval(interval);return}const left=(new Date(current.due_at)-Date.now())/1000;value.textContent=fmt(Math.ceil(left));if(left<=0){title.textContent='🔔 Timer finished';meta.textContent='Finished';el.classList.add('timer-finished');if(interval)clearInterval(interval);if(!alerted){alerted=true;notice('🔔',current.reason||'Timer finished',current.reason?'Timer completed':'Timer',wrap);try{const A=window.AudioContext||window.webkitAudioContext;if(A){const ctx=new A(),o=ctx.createOscillator(),g=ctx.createGain();o.connect(g);g.connect(ctx.destination);g.gain.value=.06;o.start();o.stop(ctx.currentTime+.15)}}catch(_){}}}else{title.textContent='⏱ Timer';meta.textContent='Running';el.classList.remove('timer-finished')}};
      const update=next=>{current={...current,...next};alerted=false;reason.textContent=current.reason?`Reason: ${current.reason}`:'';if(interval)clearInterval(interval);tick();if(current.status!=='cancelled'&&new Date(current.due_at)>Date.now())interval=setInterval(tick,250)};
      cancel.onclick=async()=>{await fetch('/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:`Cancel timer ${current.id}`,agent_type:document.getElementById('agentType')?.value||'general'})});update({...current,status:'cancelled'})};timerCards.set(String(card.id),{wrap,update});update(card);return wrap
    }
    return previousRender(card,message)
  };

  const oldAdd=window.addAssistant;if(typeof oldAdd==='function'){window.addAssistant=function(message,card){oldAdd(message,card);if(card&&(card.type==='reminder'||card.type==='schedule')){const rows=document.querySelectorAll('.assistant-row'),target=rows[rows.length-1];notice(card.type==='reminder'?'🔔':'🔁',card.text||'Reminder',card.due_at?new Date(card.due_at).toLocaleTimeString():(card.cadence||''),target)}}}
  async function pollEvents(){try{const response=await fetch('/local/events/poll');if(!response.ok)return;const data=await response.json();for(const event of data.events||[]){if(typeof window.addAssistant==='function')window.addAssistant(event.message||'Reminder',event.card||null)}}catch(_){}}
  setInterval(pollEvents,5000);setTimeout(pollEvents,1000);
})();
