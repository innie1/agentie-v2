(()=>{
  const sidebar=document.querySelector('.sidebar');
  if(!sidebar||document.getElementById('agentiePluginsButton'))return;

  const style=document.createElement('style');
  style.textContent=`
    .sidebar{position:relative;padding-bottom:72px}
    .plugins-launch{position:absolute;left:18px;right:18px;bottom:18px;display:flex;align-items:center;gap:9px;width:calc(100% - 36px);padding:9px 10px;border:1px solid transparent;border-radius:10px;background:transparent;color:var(--text);cursor:pointer;text-align:left}
    .plugins-launch:hover{background:var(--soft);border-color:var(--border)}
    .plugins-launch .plug-dot{width:24px;height:24px;border-radius:8px;display:grid;place-items:center;background:var(--soft);font-size:13px}
    .plugins-panel{position:fixed;left:242px;bottom:18px;width:min(430px,calc(100vw - 270px));max-height:min(680px,82vh);z-index:80;background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:0 18px 55px rgba(0,0,0,.18);overflow:hidden;display:none}
    .plugins-panel.open{display:block}.plugins-head{display:flex;align-items:center;justify-content:space-between;padding:15px 16px;border-bottom:1px solid var(--border)}
    .plugins-head strong{font-size:15px}.plugins-close{border:0;background:transparent;color:var(--muted);font-size:20px;cursor:pointer;line-height:1}.plugins-body{padding:14px 16px 16px;overflow:auto;max-height:calc(min(680px,82vh) - 54px)}
    .plugins-section{margin-bottom:18px}.plugins-section:last-child{margin-bottom:0}.plugins-section-title{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}.plugin-empty{font-size:13px;color:var(--muted);padding:10px 0}
    .mcp-row{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border)}.mcp-row:last-child{border-bottom:0}.mcp-icon{width:30px;height:30px;border-radius:9px;background:var(--soft);display:grid;place-items:center;flex:none;font-size:13px}
    .mcp-main{min-width:0;flex:1}.mcp-name{font-size:13px;font-weight:650}.mcp-meta{font-size:11px;color:var(--muted);margin-top:2px;line-height:1.35;overflow:hidden;text-overflow:ellipsis}.mcp-cap{font-size:10px;color:var(--muted);margin-top:4px}
    .mcp-inspect,.mcp-add{border:1px solid var(--border);background:var(--panel);color:var(--text);padding:5px 8px;border-radius:8px;font-size:11px;cursor:pointer;flex:none}.mcp-add{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}.mcp-add[disabled]{opacity:.5;cursor:default}
    .plugins-foot{display:flex;justify-content:space-between;align-items:center;margin-top:8px;font-size:11px;color:var(--muted)}.plugins-refresh{border:0;background:transparent;color:var(--muted);cursor:pointer;padding:3px}
    .mcp-approval-detail{margin-top:9px;padding:9px;border-radius:10px;background:var(--soft);font-size:12px;line-height:1.45}.mcp-approval-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.mcp-approval-actions button{border:1px solid var(--border);background:var(--panel);color:var(--text);padding:6px 10px;border-radius:9px;cursor:pointer}.mcp-approval-actions .approve-once{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}.mcp-approval-actions .always-allow{font-weight:600}.mcp-approval-note{font-size:10px;color:var(--muted);margin-top:7px;line-height:1.35}
    .web-shot{margin-top:10px;border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--soft)}.web-shot img{display:block;width:100%;max-height:520px;object-fit:contain;background:#fff}.web-shot-meta{margin-top:8px;font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis}.web-shot-excerpt{margin-top:9px;font-size:12px;line-height:1.45;color:var(--muted);white-space:pre-wrap;max-height:120px;overflow:auto}
    @media(max-width:760px){.plugins-panel{left:12px;right:12px;bottom:12px;width:auto}.plugins-launch{display:none}}
  `;
  document.head.appendChild(style);

  const button=document.createElement('button');button.id='agentiePluginsButton';button.className='plugins-launch';button.type='button';button.innerHTML='<span class="plug-dot">🔌</span><span>Plugins</span>';sidebar.appendChild(button);
  const panel=document.createElement('div');panel.className='plugins-panel';panel.id='agentiePluginsPanel';panel.innerHTML=`<div class="plugins-head"><strong>Plugins</strong><button class="plugins-close" type="button" aria-label="Close">×</button></div><div class="plugins-body"><div class="plugin-empty">Loading…</div></div>`;document.body.appendChild(panel);
  const body=panel.querySelector('.plugins-body');

  function escPlugin(value){const d=document.createElement('div');d.textContent=String(value??'');return d.innerHTML}
  function sendChat(text){const input=document.getElementById('messageInput'),send=document.getElementById('sendButton');if(!input||!send)return;input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));send.click();panel.classList.remove('open')}
  const caps=value=>(Array.isArray(value)?value:[]).slice(0,5).join(' · ');

  async function loadPlugins(){
    body.innerHTML='<div class="plugin-empty">Loading…</div>';
    try{
      const response=await fetch('/plugins/state',{cache:'no-store'});if(!response.ok)throw new Error('Could not load plugins');
      const state=await response.json();
      const skills=Array.isArray(state.plugins)?state.plugins:[],servers=Array.isArray(state.mcp_servers)?state.mcp_servers:[],presets=Array.isArray(state.mcp_presets)?state.mcp_presets:[];
      const available=presets.filter(p=>!p.installed);
      body.innerHTML=`
        <div class="plugins-section"><div class="plugins-section-title">Skills</div>${skills.length?skills.map(p=>`<div class="mcp-row"><div class="mcp-icon">${p.enabled?'✓':'○'}</div><div class="mcp-main"><div class="mcp-name">${escPlugin(p.name||p.id||'Skill')}</div><div class="mcp-meta">${escPlugin(p.description||'')}</div><div class="mcp-cap">${escPlugin(caps(p.capabilities))}</div></div></div>`).join(''):'<div class="plugin-empty">No skills registered.</div>'}</div>
        <div class="plugins-section"><div class="plugins-section-title">Connected MCP servers</div><div id="agentieMcpRows">${servers.length?servers.map(s=>`<div class="mcp-row"><div class="mcp-icon">${s.transport==='stdio'?'⌘':'↗'}</div><div class="mcp-main"><div class="mcp-name">${escPlugin(s.name)}</div><div class="mcp-meta">${s.transport==='stdio'?'Local · ':'HTTP · '}${escPlugin(s.display||'')}</div></div><button class="mcp-inspect" type="button" data-mcp="${escPlugin(s.name)}">Inspect</button></div>`).join(''):'<div class="plugin-empty">No MCP servers registered.</div>'}</div></div>
        <div class="plugins-section"><div class="plugins-section-title">Available MCP presets</div>${available.length?available.map(p=>`<div class="mcp-row"><div class="mcp-icon">＋</div><div class="mcp-main"><div class="mcp-name">${escPlugin(p.name)}</div><div class="mcp-meta">${escPlugin(p.description||'')}</div><div class="mcp-cap">${escPlugin(p.requires||'')} ${caps(p.capabilities)?'· '+escPlugin(caps(p.capabilities)):''}</div></div><button class="mcp-add" type="button" data-add-mcp="${escPlugin(p.id)}" data-command="${escPlugin(p.command||'')}">Add</button></div>`).join(''):'<div class="plugin-empty">All bundled MCP presets are already registered.</div>'}</div>
        <div class="plugins-foot"><span>${servers.length} MCP server${servers.length===1?'':'s'} · ${skills.filter(s=>s.enabled).length} active skill${skills.filter(s=>s.enabled).length===1?'':'s'}</span><button class="plugins-refresh" type="button">Refresh</button></div>`;
      body.querySelectorAll('[data-mcp]').forEach(btn=>btn.addEventListener('click',()=>sendChat(`Inspect MCP ${btn.dataset.mcp}`)));
      body.querySelectorAll('[data-add-mcp]').forEach(btn=>btn.addEventListener('click',()=>{const id=btn.dataset.addMcp,command=btn.dataset.command;if(!id||!command)return;sendChat(`Add MCP server ${id} using ${command}`)}));
      const refresh=body.querySelector('.plugins-refresh');if(refresh)refresh.onclick=loadPlugins;
    }catch(error){body.innerHTML=`<div class="plugin-empty">${escPlugin(error.message||'Could not load plugins.')}</div>`}
  }

  const previousRender=window.renderCard;
  if(typeof previousRender==='function'){
    window.renderCard=function(card,message){
      if(card&&card.type==='web_snapshot'){
        const wrap=document.createElement('div');wrap.className='card-wrap';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
        if(message){const top=document.createElement('div');top.className='card-topline';top.textContent=message;el.appendChild(top)}
        const title=document.createElement('div');title.className='card-title';title.textContent='🌐 '+String(card.title||'Website snapshot');el.appendChild(title);
        const meta=document.createElement('div');meta.className='web-shot-meta';const when=card.captured_at?new Date(card.captured_at).toLocaleString():'';meta.textContent=String(card.url||'')+' · '+(card.changed?'changed':'no meaningful change')+(when?' · '+when:'');el.appendChild(meta);
        const shot=document.createElement('div');shot.className='web-shot';const img=document.createElement('img');img.src=card.image_url||'';img.alt='Website screenshot';img.loading='lazy';shot.appendChild(img);el.appendChild(shot);
        if(card.excerpt){const excerpt=document.createElement('div');excerpt.className='web-shot-excerpt';excerpt.textContent=String(card.excerpt);el.appendChild(excerpt)}
        return wrap;
      }
      if(!card||card.type!=='mcp_approval')return previousRender(card,message);
      const wrap=document.createElement('div');wrap.className='card-wrap';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
      const title=document.createElement('div');title.className='card-title';title.textContent='🛡 MCP approval';el.appendChild(title);
      if(message){const top=document.createElement('div');top.className='card-meta';top.textContent=message;el.appendChild(top)}
      const detail=document.createElement('div');detail.className='mcp-approval-detail';detail.textContent=`${card.server} / ${card.tool}\n${JSON.stringify(card.arguments||{},null,2)}`;detail.style.whiteSpace='pre-wrap';el.appendChild(detail);
      const actions=document.createElement('div');actions.className='mcp-approval-actions';
      const approveOnce=document.createElement('button'),always=document.createElement('button'),deny=document.createElement('button');
      approveOnce.className='approve-once';approveOnce.textContent='Approve once';always.className='always-allow';always.textContent='Always allow this tool';deny.textContent='Deny';actions.append(approveOnce,always,deny);el.appendChild(actions);
      const note=document.createElement('div');note.className='mcp-approval-note';note.textContent='Always allow applies only to this MCP server and this tool. Read-only MCP tools run automatically.';el.appendChild(note);
      async function resolve(mode){
        approveOnce.disabled=true;always.disabled=true;deny.disabled=true;
        const approved=mode!=='deny',suffix=mode==='always'?':always':'';
        try{
          const r=await fetch(`/approvals/${card.approval.id}${suffix}/resolve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved})});
          if(!r.ok)throw new Error('Could not resolve approval');
          title.textContent=mode==='always'?'✓ MCP tool always allowed':approved?'✓ MCP approved once':'MCP denied';actions.remove();note.remove();
          if(approved&&card.command)setTimeout(()=>sendChat(card.command),80);
        }catch(error){approveOnce.disabled=false;always.disabled=false;deny.disabled=false;const meta=document.createElement('div');meta.className='card-meta';meta.textContent=error.message||'Approval failed.';el.appendChild(meta)}
      }
      approveOnce.onclick=()=>resolve('once');always.onclick=()=>resolve('always');deny.onclick=()=>resolve('deny');return wrap;
    };
  }

  button.onclick=()=>{panel.classList.toggle('open');if(panel.classList.contains('open'))loadPlugins()};panel.querySelector('.plugins-close').onclick=()=>panel.classList.remove('open');document.addEventListener('keydown',event=>{if(event.key==='Escape')panel.classList.remove('open')});
})();

// Persistent agent UI enhancement. Kept additive so existing cards, approvals,
// plugins, browser and computer renderers continue to own their current flows.
(()=>{
  if(window.__agentieAgentUIWired)return;window.__agentieAgentUIWired=true;
  const style=document.createElement('style');style.textContent=`.agent-row{position:relative}.agent-copy strong{display:flex!important;align-items:center;gap:6px}.agent-role-tag{display:inline-flex;max-width:112px;padding:2px 6px;border:1px solid var(--border);border-radius:999px;background:var(--soft);color:var(--muted);font-size:9px;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.agent-last-message{font-size:10px!important;color:var(--muted);margin-top:3px!important}.agent-edit{border:0;background:transparent;color:var(--muted);cursor:pointer;padding:4px;border-radius:7px}.agent-edit:hover{background:var(--soft);color:var(--text)}.agent-delete{display:none!important}.agent-menu{position:absolute;right:4px;top:34px;z-index:40;min-width:155px;padding:5px;border:1px solid var(--border);border-radius:10px;background:var(--panel);box-shadow:0 10px 28px rgba(0,0,0,.18)}.agent-menu button{display:block;width:100%;border:0;background:transparent;color:var(--text);text-align:left;padding:7px 8px;border-radius:7px;font-size:11px;cursor:pointer}.agent-menu button:hover{background:var(--soft)}.agent-menu .danger{color:#ef4444}.agent-handoff-card{width:min(520px,92vw)}.agent-handoff-flow{display:flex;align-items:center;gap:8px;margin-top:10px}.agent-handoff-person{display:flex;align-items:center;gap:7px;min-width:0}.agent-handoff-orb{width:27px;height:27px;border-radius:50%;display:grid;place-items:center;font-size:8px;font-weight:800;color:#111;flex:none}.agent-handoff-arrow{color:var(--muted);font-size:15px}.agent-handoff-role{font-size:10px;color:var(--muted)}.agent-handoff-status{margin-top:10px;padding:8px 9px;border-radius:9px;background:var(--soft);font-size:11px;color:var(--muted)}`;document.head.appendChild(style);
  const storageKey='agentie_agent_last_messages';let saved={};try{saved=JSON.parse(localStorage.getItem(storageKey)||'{}')||{}}catch(_){saved={}}
  const persist=()=>{try{localStorage.setItem(storageKey,JSON.stringify(saved))}catch(_){}};
  function initials(name){return String(name||'A').split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase()}
  function color(a){const cs=['#ff6b6b','#ffd166','#06d6a0','#4cc9f0','#5e60ce','#c77dff','#f72585','#fb8500'];let n=0;for(const ch of String(a?.id||a?.name||''))n=(n*31+ch.charCodeAt(0))>>>0;return cs[n%cs.length]}
  function activeAgent(){const row=document.querySelector('#persistentAgentList .agent-row.active');if(!row)return null;const id=row.dataset.agentId;if(id)return (window.__agentieAgents||[]).find(a=>a.id===id)||null;const raw=row.querySelector('.agent-copy strong')?.firstChild?.textContent?.trim()||'';return (window.__agentieAgents||[]).find(a=>a.name===raw)||null}
  async function editAgent(a){const oldName=a.name;const nextName=prompt('Agent name',oldName);if(nextName===null)return;const nextRole=prompt('Role / title',a.role||'general');if(nextRole===null)return;const commands=[];const cleanName=nextName.trim();const cleanRole=nextRole.trim();if(cleanName&&cleanName!==oldName)commands.push(`Rename agent ${oldName} to ${cleanName}`);const roleTarget=cleanName||oldName;if(cleanRole&&cleanRole!==a.role)commands.push(`Change agent ${roleTarget} role to ${cleanRole}`);for(const message of commands){const r=await fetch('/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,agent_type:'general',session_id:'ui:agent-edit'})});if(!r.ok)return}if(commands.length)location.reload()}
  function closeMenus(){document.querySelectorAll('.agent-menu').forEach(x=>x.remove())}
  function openMenu(row,a,del){closeMenus();const menu=document.createElement('div');menu.className='agent-menu';const editItem=document.createElement('button');editItem.type='button';editItem.textContent='Edit name & role';editItem.onclick=e=>{e.stopPropagation();menu.remove();editAgent(a)};const deleteItem=document.createElement('button');deleteItem.type='button';deleteItem.className='danger';deleteItem.textContent='Delete agent';deleteItem.onclick=e=>{e.stopPropagation();menu.remove();if(del)del.click()};menu.append(editItem,deleteItem);row.appendChild(menu)}
  function refreshRows(){const agents=window.__agentieAgents||[];document.querySelectorAll('#persistentAgentList .agent-row').forEach(row=>{let a=row.dataset.agentId?agents.find(x=>x.id===row.dataset.agentId):null;if(!a){const raw=row.querySelector('.agent-copy strong')?.textContent?.trim()||'';a=agents.find(x=>x.name===raw)}if(!a)return;row.dataset.agentId=a.id;const copy=row.querySelector('.agent-copy');const strong=copy?.querySelector('strong');if(!copy||!strong)return;strong.replaceChildren(document.createTextNode(a.name+' '));const tag=document.createElement('span');tag.className='agent-role-tag';tag.textContent=a.role||'general';strong.appendChild(tag);let sub=copy.querySelector('small');if(!sub){sub=document.createElement('small');copy.appendChild(sub)}sub.className='agent-last-message';sub.textContent=saved[a.id]||'No messages yet';if(!row.querySelector('.agent-edit')){const edit=document.createElement('button');edit.type='button';edit.className='agent-edit';edit.title='Agent options';edit.setAttribute('aria-label',`Options for ${a.name}`);edit.textContent='⋯';const del=row.querySelector('.agent-delete');edit.onclick=e=>{e.stopPropagation();openMenu(row,a,del)};if(del)row.insertBefore(edit,del);else row.appendChild(edit)}})}
  document.addEventListener('click',e=>{if(!e.target.closest('.agent-menu')&&!e.target.closest('.agent-edit'))closeMenus()});
  const oldAdd=window.addAssistant;if(typeof oldAdd==='function')window.addAssistant=function(message,card){const a=activeAgent();if(a&&message){saved[a.id]=String(message).replace(/\s+/g,' ').trim().slice(0,120);persist()}const out=oldAdd(message,card);setTimeout(refreshRows,0);return out};
  const list=document.getElementById('persistentAgentList');if(list)new MutationObserver(()=>refreshRows()).observe(list,{childList:true});setTimeout(refreshRows,80);
  const previous=window.renderCard;if(typeof previous==='function')window.renderCard=function(card,message){if(card?.type!=='agent_handoff')return previous(card,message);const wrap=document.createElement('div');wrap.className='card-wrap agent-handoff-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);const title=document.createElement('div');title.className='card-title';title.textContent='Agent handoff';el.appendChild(title);const flow=document.createElement('div');flow.className='agent-handoff-flow';for(const [agent,arrow] of [[card.from_agent,true],[card.to_agent,false]]){const person=document.createElement('div');person.className='agent-handoff-person';const orb=document.createElement('span');orb.className='agent-handoff-orb';orb.style.background=color(agent);orb.textContent=initials(agent?.name);const txt=document.createElement('div');const name=document.createElement('strong');name.textContent=agent?.name||'Agent';const role=document.createElement('div');role.className='agent-handoff-role';role.textContent=agent?.role||'';txt.append(name,role);person.append(orb,txt);flow.appendChild(person);if(arrow){const ar=document.createElement('span');ar.className='agent-handoff-arrow';ar.textContent='→';flow.appendChild(ar)}}el.appendChild(flow);const status=document.createElement('div');status.className='agent-handoff-status';const state=card.team_job?.status||'queued';status.textContent=`${card.reason||'Specialty matched'} · ${state} · ${card.team_job?.id||''}`;el.appendChild(status);return wrap};
})();
