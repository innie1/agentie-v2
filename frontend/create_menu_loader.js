(()=>{
  if(window.__agentieCreateMenuLoader)return;window.__agentieCreateMenuLoader=true;

  const style=document.createElement('style');style.textContent=`
  .agentie-choice-list,.platform-options,.n4-agent-picks{display:grid!important;grid-template-columns:1fr!important;gap:0!important;border:1px solid var(--border)!important;border-radius:13px!important;overflow:hidden!important;background:var(--soft)!important}.agentie-choice-row,.platform-option,.n4-agent-pick{min-height:46px!important;box-sizing:border-box!important;display:flex!important;align-items:center!important;gap:10px!important;padding:10px 12px!important;margin:0!important;border:0!important;border-bottom:1px solid var(--border)!important;border-radius:0!important;background:transparent!important;color:var(--text)!important;cursor:pointer!important}.agentie-choice-row:last-child,.platform-option:last-child,.n4-agent-pick:last-child{border-bottom:0!important}.agentie-choice-row:hover,.platform-option:hover,.n4-agent-pick:hover{background:color-mix(in srgb,var(--soft) 70%,var(--text) 5%)!important}.agentie-choice-row input,.platform-option>input,.n4-agent-pick>input{width:17px!important;height:17px!important;flex:0 0 17px!important;margin:0!important;accent-color:#0b84ff!important}.agentie-choice-row.selected{background:color-mix(in srgb,#0b84ff 10%,var(--soft))!important}.agentie-choice-copy{min-width:0;display:block}.agentie-choice-copy strong{display:block;font-size:12px}.agentie-choice-copy small{display:block;margin-top:2px;font-size:9px;color:var(--muted)}
  .employee-profile-card:not(.employee-profile-form){width:min(520px,94vw)!important;max-height:none!important;overflow:visible!important;border-radius:20px!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-cover{height:76px!important;border-radius:19px 19px 15px 15px!important;background:linear-gradient(180deg,color-mix(in srgb,var(--soft) 88%,var(--panel)),var(--panel))!important}.employee-profile-card:not(.employee-profile-form) .employee-avatar-shell{top:36px!important;width:88px!important;height:88px!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-main{padding:54px 28px 24px!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-name{font-size:21px!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-role{font-size:13px!important;margin-top:4px!important;color:var(--text)!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-personality,.employee-profile-card:not(.employee-profile-form) .employee-profile-stats{display:none!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-sections{display:block!important;margin-top:10px!important;text-align:center!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-section{display:none!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-section:first-child{display:block!important;border:0!important;background:transparent!important;padding:0!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-section:first-child>strong{display:none!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-section:first-child>div{max-width:390px;margin:auto;color:var(--muted);font-size:12px!important;line-height:1.5!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-actions{margin-top:18px!important}.employee-profile-inline .employee-profile-actions{margin-top:12px!important}.agentie-profile-delete{border-color:color-mix(in srgb,#ef4444 45%,var(--border))!important;color:#ef4444!important;background:transparent!important}.employee-profile-form{width:min(520px,94vw)!important;max-height:88vh!important;overflow:auto!important;border-radius:20px!important}.employee-profile-form .employee-field textarea{min-height:62px!important}.employee-profile-form .employee-field[data-agentie-user-instructions] textarea{min-height:78px!important}.agentie-details-status{font-size:10px;color:var(--muted);margin-top:9px}.agentie-details-status.error{color:#ef4444}.agentie-shared-tool-note{margin:0 0 12px;padding:10px 11px;border:1px solid var(--border);border-radius:11px;background:var(--soft);font-size:11px;line-height:1.45;color:var(--muted)}.agentie-shared-tool-note strong{display:block;color:var(--text);margin-bottom:2px}.agentie-shared-access-sentinel{display:none!important}@media(max-width:560px){.employee-profile-card:not(.employee-profile-form){width:min(460px,94vw)!important}.employee-profile-card:not(.employee-profile-form) .employee-profile-main{padding-left:20px!important;padding-right:20px!important}}
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

  // Connected tools are shared once at workspace level. Keep the old per-agent
  // access editor from mounting without continuously watching or rewriting the DOM.
  function ensureSharedToolCatalog(){
    const body=document.querySelector('#agentiePluginsPanel .plugins-body');if(!body)return;
    body.querySelectorAll('.agent-access-box:not(.agentie-shared-access-sentinel)').forEach(el=>el.remove());
    if(!body.querySelector('.agentie-shared-access-sentinel')){const sentinel=document.createElement('div');sentinel.className='agent-access-box agentie-shared-access-sentinel';sentinel.setAttribute('aria-hidden','true');body.prepend(sentinel)}
    if(!body.querySelector('.agentie-shared-tool-note')){const note=document.createElement('div');note.className='agentie-shared-tool-note';note.innerHTML='<strong>Shared workspace tools</strong>Connected tools and enabled capabilities are available to every agent automatically. Agents choose what to use when a task fits their job; consequential actions still require approval.';body.prepend(note)}
  }
  const pluginPanel=document.getElementById('agentiePluginsPanel');if(pluginPanel)ensureSharedToolCatalog();
  document.getElementById('agentiePluginsButton')?.addEventListener('click',()=>{ensureSharedToolCatalog();setTimeout(ensureSharedToolCatalog,180)});

  const clean=value=>String(value??'').replace(/\s+/g,' ').trim();
  function resolveAgent(value){const key=clean(value).casefold?.()||clean(value).toLowerCase();return (window.__agentieAgents||[]).find(a=>String(a.id||'').toLowerCase()===key||String(a.name||'').toLowerCase()===key)||null}
  function agentForModal(modal){const name=modal?.querySelector('.employee-profile-name')?.textContent?.trim()||modal?.querySelector('.employee-profile-form h3')?.textContent?.replace(/^Edit\s+/i,'').replace(/\s+·\s+Details$/i,'').trim();const active=document.querySelector('#persistentAgentList .agent-row.active')?.dataset?.agentId;return resolveAgent(name)||resolveAgent(active)}
  async function runProfile(message,agent){const response=await fetch('/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,agent_type:'general',session_id:`ui:employee-profile:${agent?.id||'agent'}`})});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||data.message||'Request failed');return data}
  function cardFrom(data){return data?.card||data?.result?.card||null}
  async function requestDelete(agent,modal){
    if(!agent)return;const button=modal?.querySelector('.agentie-profile-delete');if(button)button.disabled=true;
    try{const data=await runProfile(`Delete agent ${agent.id}`,agent);modal?.remove();if(typeof window.addAssistant==='function')window.addAssistant(data.message||`Delete ${agent.name}`,cardFrom(data));else window.agentieNotice?.('🗑️','Delete agent',data.message||`Delete ${agent.name}`,null,'agent-delete')}
    catch(error){if(button)button.disabled=false;alert(error.message||'Could not start deletion.')}
  }
  function addDeleteButton(actions,agent,modal){if(!actions||actions.querySelector('.agentie-profile-delete'))return;const button=document.createElement('button');button.type='button';button.className='agentie-profile-delete';button.textContent='Delete agent';button.onclick=()=>requestDelete(agent,modal);actions.appendChild(button)}
  async function augmentDetailsForm(form,modal,agent){
    if(!form||!agent||form.dataset.agentieUnified==='1')return;form.dataset.agentieUnified='1';
    const heading=form.querySelector('h3');if(heading&&heading.textContent!==`${agent.name} · Details`)heading.textContent=`${agent.name} · Details`;
    const intro=form.querySelector('p');const introText='Identity, role and durable working instructions. Workspace tools are shared automatically.';if(intro&&intro.textContent!==introText)intro.textContent=introText;
    const actions=form.querySelector('.employee-profile-form-actions');if(!actions)return;
    const instructionField=document.createElement('div');instructionField.className='employee-field';instructionField.dataset.agentieUserInstructions='1';const label=document.createElement('label');label.textContent='Instructions';const textarea=document.createElement('textarea');textarea.placeholder='Optional durable instructions for how this agent should work…';instructionField.append(label,textarea);form.insertBefore(instructionField,actions);
    const status=document.createElement('div');status.className='agentie-details-status';form.insertBefore(status,actions);addDeleteButton(actions,agent,modal);
    let originalManual='';try{const data=await runProfile(`Show ${agent.id} instructions`,agent);const card=cardFrom(data);originalManual=String(card?.manual_instructions||'').trim();textarea.value=originalManual}catch(_){textarea.value=''}
    const save=[...actions.querySelectorAll('button')].find(btn=>btn.classList.contains('primary')||btn.textContent.trim()==='Save profile');if(!save)return;const originalSave=save.onclick;if(save.textContent!=='Save details')save.textContent='Save details';
    save.onclick=async event=>{const nextManual=textarea.value.trim();if(nextManual!==originalManual){save.disabled=true;status.classList.remove('error');status.textContent='Saving instructions…';try{if(nextManual){await runProfile(`Set agent ${agent.id} instructions to ${nextManual}`,agent);originalManual=nextManual}else if(originalManual){status.classList.add('error');status.textContent='To replace existing instructions, enter the new instruction text.';save.disabled=false;return}}catch(error){status.classList.add('error');status.textContent=error.message||'Could not save instructions.';save.disabled=false;return}save.disabled=false}if(typeof originalSave==='function')return originalSave.call(save,event)};
  }
  function polishAgentProfile(modal){
    if(!modal)return;const agent=agentForModal(modal);if(!agent)return;
    const card=modal.querySelector('.employee-profile-card:not(.employee-profile-form)');if(card&&card.dataset.agentiePolished!=='1'){card.dataset.agentiePolished='1';const actions=card.querySelector('.employee-profile-actions');if(actions){const edit=actions.querySelector('button.primary');if(edit&&edit.textContent.trim()!=='Edit details')edit.textContent='Edit details';[...actions.querySelectorAll('button')].filter(btn=>btn.textContent.trim()==='Instructions').forEach(btn=>btn.remove());addDeleteButton(actions,agent,modal)}}
    const form=modal.querySelector('.employee-profile-form');if(form)augmentDetailsForm(form,modal,agent)
  }
  function polishOpenProfiles(){document.querySelectorAll('.employee-profile-modal').forEach(polishAgentProfile)}
  let polishTimerA=null,polishTimerB=null;
  function scheduleProfilePolish(){
    if(polishTimerA)clearTimeout(polishTimerA);if(polishTimerB)clearTimeout(polishTimerB);
    polishTimerA=setTimeout(()=>{polishTimerA=null;polishOpenProfiles()},0);
    polishTimerB=setTimeout(()=>{polishTimerB=null;polishOpenProfiles()},160);
  }
  // Profile enhancement is user-event driven. There is deliberately no body-wide
  // MutationObserver because Agentie's chat/sidebar polling mutates the DOM often.
  document.addEventListener('click',scheduleProfilePolish,false);
  window.__agentiePolishOpenProfiles=polishOpenProfiles;
  scheduleProfilePolish();
})();
