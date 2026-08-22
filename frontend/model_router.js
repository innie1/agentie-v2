(()=>{
  if(window.__agentieModelRouterUI)return;window.__agentieModelRouterUI=true;
  const css=document.createElement('style');css.textContent=`
  .model-router-control{margin-top:8px;border:1px solid var(--border);border-radius:10px;background:var(--soft);padding:7px 8px}
  .model-router-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:6px;font-size:9px;color:var(--muted)}
  .model-router-head b{font-size:10px;color:var(--text)}
  .model-router-modes{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}
  .model-router-mode{border:1px solid var(--border);border-radius:7px;background:var(--panel);color:var(--text);padding:5px 3px;font-size:9px;cursor:pointer}
  .model-router-mode.active{background:#0b84ff;color:#fff;border-color:#0b84ff}
  .model-router-mode:disabled{opacity:.55;cursor:default}
  .model-router-detail{font-size:8px;color:var(--muted);line-height:1.35;margin-top:5px;white-space:normal}
  `;document.head.appendChild(css);

  const esc=v=>{const d=document.createElement('div');d.textContent=String(v??'');return d.innerHTML};
  async function api(url,options={}){const r=await fetch(url,options),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.message||'Request failed');return d}

  function label(mode){return mode==='local'?'Local':mode==='powerful'?'Powerful':'Auto'}
  function detailText(state){
    const local=state.local||{},cloud=state.powerful||{};
    const localState=local.available===true?'local ready':local.available===false?'local offline':'local not checked';
    const cloudState=cloud.configured?`${cloud.provider||'cloud'} ready`:`${cloud.provider||'cloud'} not configured`;
    if(state.mode==='local')return `${local.model||'local model'} · ${localState} · cloud fallback off`;
    if(state.mode==='powerful')return `${cloud.provider||'powerful'} · ${cloudState}`;
    return `${local.model||'local model'} first · ${localState} · escalates when needed`;
  }

  async function refresh(control,verify=false){
    try{
      const state=await api(`/platform/model-routing/status?verify=${verify?'true':'false'}`,{cache:'no-store'});
      control.dataset.mode=state.mode||'auto';
      for(const b of control.querySelectorAll('.model-router-mode'))b.classList.toggle('active',b.dataset.mode===state.mode);
      const title=control.querySelector('[data-current]');if(title)title.textContent=label(state.mode||'auto');
      const detail=control.querySelector('.model-router-detail');if(detail)detail.textContent=detailText(state);
      control.title='Local keeps AI reasoning on this computer. Auto prefers local and escalates complex work. Powerful always uses the configured cloud model.';
      return state;
    }catch(e){const detail=control.querySelector('.model-router-detail');if(detail)detail.textContent=e.message;return null}
  }

  async function setMode(control,mode){
    for(const b of control.querySelectorAll('.model-router-mode'))b.disabled=true;
    try{
      await api('/platform/model-routing/mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode})});
      await refresh(control,true);
    }catch(e){const detail=control.querySelector('.model-router-detail');if(detail)detail.textContent=e.message}
    finally{for(const b of control.querySelectorAll('.model-router-mode'))b.disabled=false}
  }

  function install(){
    const sidebar=document.querySelector('.sidebar'),search=sidebar?.querySelector('.agent-search');if(!sidebar||!search)return;
    let control=sidebar.querySelector('.model-router-control');
    if(!control){
      control=document.createElement('div');control.className='model-router-control';
      control.innerHTML=`<div class="model-router-head"><b>AI model</b><span data-current>Auto</span></div><div class="model-router-modes">${['local','auto','powerful'].map(m=>`<button type="button" class="model-router-mode" data-mode="${esc(m)}">${label(m)}</button>`).join('')}</div><div class="model-router-detail">Checking model routing…</div>`;
      search.after(control);
      for(const b of control.querySelectorAll('.model-router-mode'))b.onclick=()=>setMode(control,b.dataset.mode);
      control.addEventListener('dblclick',()=>refresh(control,true));
      refresh(control,true);
    }
  }
  let queued=false;new MutationObserver(()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;install()})}).observe(document.body,{childList:true,subtree:true});setTimeout(install,120);
})();
