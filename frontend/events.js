(() => {
  const style=document.createElement('style');
  style.textContent=`.notice-rail{position:fixed;right:14px;bottom:92px;z-index:50;display:grid;gap:7px;max-width:270px}.notice-chip{display:grid;grid-template-columns:28px 1fr 22px;gap:7px;align-items:center;padding:8px 9px;border:1px solid var(--border);border-radius:12px;background:var(--panel);box-shadow:0 8px 24px rgba(0,0,0,.12);font-size:11px}.notice-chip button{border:0;background:transparent;color:var(--muted);cursor:pointer;padding:2px}.notice-main{overflow:hidden}.notice-main strong,.notice-main small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.notice-main small{color:var(--muted);margin-top:2px}.timer-card-placeholder,.job-card-placeholder{display:none!important}.job-card{width:min(560px,92vw)}.job-steps{display:grid;gap:6px;margin-top:10px}.job-step{display:grid;grid-template-columns:18px 1fr auto;gap:7px;align-items:center;padding:7px 8px;background:var(--soft);border-radius:9px;font-size:12px}.job-step small{display:block;color:var(--muted);font-size:10px;margin-top:2px}.job-final{white-space:pre-wrap;font-size:12px;line-height:1.45;margin-top:10px;max-height:230px;overflow:auto}.job-trace{display:none;white-space:pre-wrap;font:10px ui-monospace,SFMono-Regular,Menlo,monospace;max-height:180px;overflow:auto;margin-top:8px;padding:8px;background:var(--soft);border-radius:9px}.web-search-card{width:min(680px,92vw)}.web-query{font-size:13px;margin-top:7px}.source-list{display:grid;gap:7px;margin-top:11px}.source-row{display:grid;grid-template-columns:34px minmax(0,1fr);gap:9px;padding:9px;border-radius:10px;background:var(--soft)}.source-id{font-size:11px;font-weight:700;color:var(--muted)}.source-row a{color:var(--text);text-decoration:none;font-weight:650;font-size:13px}.source-row a:hover{text-decoration:underline}.source-domain{font-size:10px;color:var(--muted);margin-top:2px}.source-snippet{font-size:11px;line-height:1.45;margin-top:5px;color:var(--muted)}.source-meta{font-size:11px;color:var(--muted);margin-top:8px}`;
  document.head.appendChild(style);
  const rail=document.createElement('div');rail.className='notice-rail';document.body.appendChild(rail);
  const timerCards=new Map(),jobCards=new Map(),noticeKeys=new Set();
  const send=document.getElementById('sendButton');
  if(send){try{Object.defineProperty(send,'disabled',{configurable:true,get:()=>false,set:()=>{}})}catch(_){send.disabled=false}}

  function trimNotices(){while(rail.children.length>5)rail.firstElementChild?.remove()}
  function notice(icon,title,detail,target,key){
    const dedupe=String(key||`${icon}|${title}|${detail||''}`);if(noticeKeys.has(dedupe))return null;noticeKeys.add(dedupe);
    const n=document.createElement('div');n.className='notice-chip';n.dataset.noticeKey=dedupe;n.innerHTML=`<div>${icon}</div><div class="notice-main"><strong></strong><small></small></div><button title="Dismiss" aria-label="Dismiss notification">×</button>`;
    n.querySelector('strong').textContent=title;n.querySelector('small').textContent=detail||'';
    n.querySelector('.notice-main').style.cursor=target?'pointer':'default';
    if(target)n.querySelector('.notice-main').onclick=()=>target.scrollIntoView({behavior:'smooth',block:'center'});
    n.querySelector('button').onclick=()=>n.remove();rail.appendChild(n);trimNotices();return n
  }
  window.agentieNotice=notice;

  const callAgent=async(message)=>{const r=await fetch('/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,agent_type:document.getElementById('agentType')?.value||'general'})});if(!r.ok)throw Error('Agent request failed');return r.json()};
  const previousRender=window.renderCard;

  function renderWebSearch(card){
    const wrap=document.createElement('div');wrap.className='card-wrap web-search-card';
    const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
    const title=document.createElement('div');title.className='card-title';title.textContent='🌐 Web sources';el.appendChild(title);
    const q=document.createElement('div');q.className='web-query';q.textContent=card.query||'';el.appendChild(q);
    const list=document.createElement('div');list.className='source-list';
    (card.sources||[]).forEach(source=>{
      const row=document.createElement('div');row.className='source-row';
      const sid=document.createElement('div');sid.className='source-id';sid.textContent=`[${source.id||'?'}]`;
      const body=document.createElement('div');const a=document.createElement('a');a.href=source.url||'#';a.target='_blank';a.rel='noopener noreferrer';a.textContent=source.title||source.url||'Source';body.appendChild(a);
      const domain=document.createElement('div');domain.className='source-domain';domain.textContent=source.domain||'';body.appendChild(domain);
      if(source.snippet){const snippet=document.createElement('div');snippet.className='source-snippet';snippet.textContent=source.snippet;body.appendChild(snippet)}
      row.append(sid,body);list.appendChild(row);
    });
    el.appendChild(list);const meta=document.createElement('div');meta.className='source-meta';meta.textContent=`${(card.sources||[]).length} source${(card.sources||[]).length===1?'':'s'} · ${Number(card.provider_calls||0)} model call${Number(card.provider_calls||0)===1?'':'s'}`;el.appendChild(meta);return wrap
  }

  function renderJob(card,titleText='🧠 Agent job'){
    const existing=jobCards.get(String(card.id));if(existing&&document.body.contains(existing.wrap)){existing.update(card);const p=document.createElement('span');p.className='job-card-placeholder';return p}
    const wrap=document.createElement('div');wrap.className='card-wrap job-card';wrap.dataset.jobId=String(card.id);
    const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
    const title=document.createElement('div');title.className='card-title';title.textContent=titleText;el.appendChild(title);
    const meta=document.createElement('div');meta.className='card-meta';el.appendChild(meta);
    const progress=document.createElement('div');progress.className='progress';progress.innerHTML='<div></div>';el.appendChild(progress);
    const steps=document.createElement('div');steps.className='job-steps';el.appendChild(steps);
    const actions=document.createElement('div');actions.className='actions';const traceBtn=document.createElement('button');traceBtn.textContent='Trace';const cancelBtn=document.createElement('button');cancelBtn.textContent='Cancel';actions.append(traceBtn,cancelBtn);el.appendChild(actions);
    const trace=document.createElement('div');trace.className='job-trace';el.appendChild(trace);const final=document.createElement('div');final.className='job-final';el.appendChild(final);
    let current={...card},poll=null,notified=false;const icon=s=>({queued:'○',running:'●',completed:'✓',failed:'!',cancelled:'×'})[s]||'○';
    const update=next=>{current={...current,...next};const total=current.total_steps||0,done=current.completed_steps||0;meta.textContent=`${current.status} · ${done}/${total} steps · ${current.provider_calls||0}/${current.budget_provider_calls||0} agent-call budget`;progress.firstElementChild.style.width=`${total?Math.round(done/total*100):0}%`;steps.replaceChildren();(current.steps||[]).forEach(s=>{const row=document.createElement('div');row.className='job-step';const a=document.createElement('span');a.textContent=icon(s.status);const mid=document.createElement('div');const strong=document.createElement('strong');strong.textContent=s.title||s.id;const small=document.createElement('small');small.textContent=s.specialist||'general';mid.append(strong,small);const stat=document.createElement('span');stat.textContent=s.status;row.append(a,mid,stat);steps.appendChild(row)});final.textContent=current.final_output||current.error||'';cancelBtn.style.display=['completed','failed','cancelled'].includes(current.status)?'none':'';if(['completed','failed','cancelled'].includes(current.status)){if(poll)clearInterval(poll);if(!notified){notified=true;notice(current.status==='completed'?'✅':'⚠️',current.status==='completed'?'Job completed':'Job stopped',current.goal||current.id,wrap,`job:${current.id}:${current.status}`)}}};
    const refresh=async()=>{try{const d=await callAgent(`job status ${current.id}`);if(d.card&&d.card.type==='job_progress')update(d.card)}catch(_){}};
    traceBtn.onclick=async()=>{trace.style.display=trace.style.display==='block'?'none':'block';if(trace.style.display==='block'){try{const d=await callAgent(`job trace ${current.id}`);trace.textContent=(d.card?.events||[]).map(e=>`${e.created_at} · ${e.message}`).join('\n')}catch(_){trace.textContent='Trace unavailable.'}}};
    cancelBtn.onclick=async()=>{try{const d=await callAgent(`cancel job ${current.id}`);if(d.card)update(d.card)}catch(_){}};
    jobCards.set(String(card.id),{wrap,update});update(card);if(!['completed','failed','cancelled'].includes(current.status))poll=setInterval(refresh,1500);return wrap
  }

  window.renderCard=function(card,message){
    if(card&&card.type==='web_search')return renderWebSearch(card);
    if(card&&card.type==='timer'&&card.id){
      const existing=timerCards.get(String(card.id));if(existing&&document.body.contains(existing.wrap)){existing.update(card);const p=document.createElement('span');p.className='timer-card-placeholder';return p}
      const wrap=document.createElement('div');wrap.className='card-wrap';wrap.dataset.timerId=String(card.id);const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);const title=document.createElement('div');title.className='card-title';el.appendChild(title);const value=document.createElement('div');value.className='card-value';el.appendChild(value);const meta=document.createElement('div');meta.className='card-meta';el.appendChild(meta);const reason=document.createElement('div');reason.className='card-meta';el.appendChild(reason);const actions=document.createElement('div');actions.className='actions';const cancel=document.createElement('button');cancel.textContent='Cancel';actions.appendChild(cancel);el.appendChild(actions);
      let current={...card},interval=null,alerted=false;const fmt=sec=>{sec=Math.max(0,Math.floor(Number(sec)||0));const h=Math.floor(sec/3600),m=Math.floor(sec%3600/60),s=sec%60;return(h?[h,m,s]:[m,s]).map(v=>String(v).padStart(2,'0')).join(':')};
      const tick=()=>{if(current.status==='cancelled'){title.textContent='⏱ Timer';value.textContent='00:00';meta.textContent='Cancelled';el.classList.remove('timer-finished');if(interval)clearInterval(interval);return}const left=(new Date(current.due_at)-Date.now())/1000;value.textContent=fmt(Math.ceil(left));if(left<=0){title.textContent='🔔 Timer finished';meta.textContent='Finished';el.classList.add('timer-finished');if(interval)clearInterval(interval);if(!alerted){alerted=true;notice('🔔',current.reason||'Timer finished',current.reason?'Timer completed':'Timer',wrap,`timer:${current.id}:${current.due_at}`);try{const A=window.AudioContext||window.webkitAudioContext;if(A){const ctx=new A(),o=ctx.createOscillator(),g=ctx.createGain();o.connect(g);g.connect(ctx.destination);g.gain.value=.06;o.start();o.stop(ctx.currentTime+.15)}}catch(_){}}}else{title.textContent='⏱ Timer';meta.textContent='Running';el.classList.remove('timer-finished')}};
      const update=next=>{const oldDue=current.due_at;current={...current,...next};if(current.due_at!==oldDue)alerted=false;reason.textContent=current.reason?`Reason: ${current.reason}`:'';if(interval)clearInterval(interval);tick();if(current.status!=='cancelled'&&new Date(current.due_at)>Date.now())interval=setInterval(tick,250)};
      cancel.onclick=async()=>{try{await callAgent(`Cancel timer ${current.id}`);update({...current,status:'cancelled'})}catch(_){meta.textContent='Could not cancel'} };timerCards.set(String(card.id),{wrap,update});update(card);return wrap
    }
    if(card&&card.type==='job_progress'&&card.id)return renderJob(card,card.steps?.some(s=>s.specialist==='deep_research')?'🔎 Deep research':'🧠 Agent job');
    if(card&&card.type==='routine_run'&&card.job?.id)return renderJob(card.job,`🔁 ${card.routine_name||'Routine run'}`);
    if(card&&card.type==='job_trace'){const wrap=document.createElement('div');wrap.className='card-wrap job-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);const title=document.createElement('div');title.className='card-title';title.textContent=`🧾 Job trace · ${card.id}`;el.appendChild(title);const body=document.createElement('div');body.className='job-trace';body.style.display='block';body.textContent=(card.events||[]).map(e=>`${e.created_at} · ${e.message}`).join('\n');el.appendChild(body);return wrap}
    return previousRender(card,message)
  };

  async function pollEvents(){
    try{
      const response=await fetch('/local/events/poll');if(!response.ok)return;const data=await response.json();
      for(const event of data.events||[]){
        const card=event.card||{};
        if(card.type==='reminder'||card.type==='schedule'){
          const key=`${card.type}:${card.id||card.text||''}:${card.due_at||card.last_fired_at||card.cadence||''}`;
          notice(card.type==='reminder'?'🔔':'🔁',card.text||'Reminder',card.due_at?new Date(card.due_at).toLocaleTimeString():(card.cadence||''),null,key);
          continue;
        }
        if(card.type==='routine_run'&&card.job){
          if(typeof window.addAssistant==='function')window.addAssistant('',card);
          const target=document.querySelector(`[data-job-id="${CSS.escape(String(card.job.id))}"]`);
          notice('🔁',card.routine_name||'Routine started','Running in background',target,`routine:${card.routine_id}:${card.job.id}`);
          continue;
        }
        if(typeof window.addAssistant==='function')window.addAssistant(event.message||'Agentie event',card||null);
      }
    }catch(_){}
  }
  setInterval(pollEvents,5000);setTimeout(pollEvents,1000);
})();
