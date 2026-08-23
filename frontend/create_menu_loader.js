(()=>{
  if(window.__agentieCreateMenuLoader)return;window.__agentieCreateMenuLoader=true;

  const style=document.createElement('style');style.textContent=`
  .agentie-choice-list,.platform-options,.n4-agent-picks{display:grid!important;grid-template-columns:1fr!important;gap:0!important;border:1px solid var(--border)!important;border-radius:13px!important;overflow:hidden!important;background:var(--soft)!important}.agentie-choice-row,.platform-option,.n4-agent-pick{min-height:46px!important;box-sizing:border-box!important;display:flex!important;align-items:center!important;gap:10px!important;padding:10px 12px!important;margin:0!important;border:0!important;border-bottom:1px solid var(--border)!important;border-radius:0!important;background:transparent!important;color:var(--text)!important;cursor:pointer!important}.agentie-choice-row:last-child,.platform-option:last-child,.n4-agent-pick:last-child{border-bottom:0!important}.agentie-choice-row:hover,.platform-option:hover,.n4-agent-pick:hover{background:color-mix(in srgb,var(--soft) 70%,var(--text) 5%)!important}.agentie-choice-row input,.platform-option>input,.n4-agent-pick>input{width:17px!important;height:17px!important;flex:0 0 17px!important;margin:0!important;accent-color:#0b84ff!important}.agentie-choice-row.selected{background:color-mix(in srgb,#0b84ff 10%,var(--soft))!important}.agentie-choice-copy{min-width:0;display:block}.agentie-choice-copy strong{display:block;font-size:12px}.agentie-choice-copy small{display:block;margin-top:2px;font-size:9px;color:var(--muted)}
  `;document.head.appendChild(style);

  let loading=null;
  function loadCreateMenu(){
    if(window.__agentieOpenCreateMenu)return Promise.resolve();
    if(loading)return loading;
    loading=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/platform-create-menu.js?v=2';script.async=true;script.onload=resolve;script.onerror=()=>reject(new Error('Create menu failed to load.'));document.head.appendChild(script)}).finally(()=>{loading=null});
    return loading;
  }
  window.addEventListener('click',event=>{
    const plus=event.target.closest?.('.agent-create');
    if(!plus)return;
    event.preventDefault();event.stopImmediatePropagation();
    loadCreateMenu().then(()=>window.__agentieOpenCreateMenu?.(plus)).catch(()=>window.agentieNotice?.('⚠️','Create','Creation menu could not load. Please try again.',null,'create-menu-load'));
  },true);
})();