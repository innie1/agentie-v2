(() => {
  const style=document.createElement('style');
  style.textContent=`
    .job-card{width:min(560px,92vw)}
    .job-steps{display:grid;gap:6px;margin-top:10px}
    .job-step{display:grid;grid-template-columns:18px 1fr auto;gap:7px;align-items:center;padding:7px 8px;background:var(--soft);border-radius:9px;font-size:12px}
    .job-step small{color:var(--muted)}
    .job-trace{max-height:180px;overflow:auto;margin-top:9px;padding:8px;border:1px solid var(--border);border-radius:9px;font-size:11px;display:none}
    .job-final{margin-top:10px;white-space:pre-wrap;font-size:12px;line-height:1.45}
  `;document.head.appendChild(style);

  const oldRender=window.renderCard;
  const pollers=new Map();
  const icon=s=>({queued:'○',running:'●',completed:'✓',failed:'!',cancelled:'×'})[s]||'○';

  function renderJob(c){
    const wrap=document.createElement('div');wrap.className='card-wrap job-card';
    const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
    const title=document.createElement('div');title.className='card-title';title.textContent='🧠 Agent job';el.appendChild(title);
    const meta=document.createElement('div');meta.className='card-meta';el.appendChild(meta);
    const progress=document.createElement('div');progress.className='progress';progress.innerHTML='<div></div>';el.appendChild(progress);
    const steps=document.createElement('div');steps.className='job-steps';el.appendChild(steps);
    const actions=document.createElement('div');actions.className='actions';el.appendChild(actions);
    const traceBtn=document.createElement('button');traceBtn.textContent='Trace';actions.appendChild(traceBtn);
    const cancelBtn=document.createElement('button');cancelBtn.textContent='Cancel';actions.appendChild(cancelBtn);
    const trace=document.createElement('div');trace.className='job-trace';el.appendChild(trace);
    const final=document.createElement('div');final.className='job-final';el.appendChild(final);
    let current={...c};

    const draw=job=>{
      current=job;const total=job.total_steps||0,done=job.completed_steps||0;
      meta.textContent=`${job.status} · ${done}/${total} steps · budget ${job.provider_calls||0}/${job.budget_provider_calls||0} agent calls`;
      progress.firstElementChild.style.width=`${total?Math.round(done/total*100):0}%`;
      steps.replaceChildren();(job.steps||[]).forEach(s=>{const row=document.createElement('div');row.className='job-step';row.innerHTML=`<span>${icon(s.status)}</span><span><strong></strong><small></small></span><small>${s.status}</small>`;row.querySelector('strong').textContent=s.title||s.id;row.querySelector('span small').textContent=s.specialist||'general';steps.appendChild(row)});
      cancelBtn.style.display=['completed','failed','cancelled'].includes(job.status)?'none':'';
      final.textContent=job.final_output||job.error||'';
      if(['completed','failed','cancelled'].includes(job.status)){const t=pollers.get(job.id);if(t){clearInterval(t);pollers.delete(job.id)}if(window.agentieNotice)window.agentieNotice(job.status==='completed'?'✅':'⚠️',job.status==='completed'?'Job completed':'Job stopped',job.goal||job.id,wrap)}
    };

    const refresh=async()=>{try{const r=await fetch(`/jobs/${encodeURIComponent(current.id)}`);if(!r.ok)return;draw(await r.json())}catch(_){}};
    traceBtn.onclick=async()=>{trace.style.display=trace.style.display==='block'?'none':'block';if(trace.style.display==='block'){const r=await fetch(`/jobs/${encodeURIComponent(current.id)}/events`);const d=await r.json();trace.textContent=(d.events||[]).map(e=>`${e.created_at} · ${e.message}`).join('\n')}};
    cancelBtn.onclick=async()=>{await fetch(`/jobs/${encodeURIComponent(current.id)}/cancel`,{method:'POST'});refresh()};
    draw(current);if(!['completed','failed','cancelled'].includes(current.status)){pollers.set(current.id,setInterval(refresh,1500));setTimeout(refresh,300)}return wrap;
  }

  window.renderCard=function(card,message){if(card&&card.type==='job_progress')return renderJob(card);return oldRender(card,message)};
})();
