(()=>{
  if(window.__agentieNavigationConnect)return;window.__agentieNavigationConnect=true;

  const css=document.createElement('style');css.textContent=`
    .plugins-launch{bottom:58px!important}
    .agentie-connected-profile{position:absolute;left:18px;right:18px;bottom:12px;z-index:90}
    .agentie-connected-profile-button{width:100%;display:flex;align-items:center;gap:9px;border:1px solid transparent;background:transparent;color:var(--text);border-radius:10px;padding:8px 10px;cursor:pointer;text-align:left}
    .agentie-connected-profile-button:hover{background:var(--soft);border-color:var(--border)}
    .agentie-connected-profile-icon{width:25px;height:25px;border-radius:50%;display:grid;place-items:center;background:var(--soft);border:1px solid var(--border);font-size:12px}
    .agentie-connected-profile-menu{position:absolute;left:0;right:0;bottom:calc(100% + 6px);display:none;z-index:18000;border:1px solid var(--border);border-radius:11px;background:var(--panel);padding:5px;box-shadow:0 16px 42px rgba(0,0,0,.26)}
    .agentie-connected-profile-menu.open{display:grid}
    .agentie-connected-profile-menu button{border:0;background:transparent;color:var(--text);border-radius:8px;text-align:left;padding:8px 9px;font-size:10px;cursor:pointer}
    .agentie-connected-profile-menu button:hover{background:var(--soft)}
    .agentie-connected-plugin-tools{display:grid;grid-template-columns:1fr 1fr;gap:7px;padding:10px 16px;border-bottom:1px solid var(--border);background:var(--panel)}
    .agentie-connected-plugin-tools-title{grid-column:1/-1;font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
    .agentie-connected-plugin-tools button{border:1px solid var(--border);border-radius:9px;background:var(--soft);color:var(--text);padding:8px 9px;font-size:10px;text-align:left;cursor:pointer}
    .agentie-connected-plugin-tools button:hover{background:var(--panel)}
    .sidebar>.platform-activity-launch,.sidebar>.platform-skills-launch,.sidebar>.pa-automation-launch,.sidebar>.n4-auto,.sidebar>.n4-market,.sidebar>.n4-chats,.sidebar>.platform-chats-launch{display:none!important}
    .agentie-connected-group-head{display:flex;align-items:center;gap:10px;margin:2px 0 18px;padding-bottom:13px;border-bottom:1px solid var(--border)}
    .agentie-connected-group-stack{position:relative;width:42px;height:34px;flex:none}
    .agentie-connected-group-dot{position:absolute;width:25px;height:25px;border-radius:50%;border:2px solid var(--panel);display:grid;place-items:center;font-size:7px;font-weight:800;color:#111;box-shadow:0 1px 4px rgba(0,0,0,.16)}
    .agentie-connected-group-dot:nth-child(1){left:0;top:5px}.agentie-connected-group-dot:nth-child(2){left:11px;top:0}.agentie-connected-group-dot:nth-child(3){left:17px;top:9px}
    .agentie-connected-group-copy strong,.agentie-connected-group-copy small{display:block}.agentie-connected-group-copy strong{font-size:14px}.agentie-connected-group-copy small{font-size:10px;color:var(--muted);margin-top:2px}
    .agentie-connected-group-author{font-size:10px;font-weight:700;color:var(--muted);margin:0 0 3px 2px}.agentie-connected-group-error{font-size:11px;color:#ef4444;margin:10px 0}
  `;document.head.appendChild(css);

  const state={group:null,groups:[],poll:null,loading:false};
  const COLORS=['#ff6b6b','#ffd166','#06d6a0','#4cc9f0','#5e60ce','#c77dff','#f72585','#fb8500'];
  const initials=name=>String(name||'A').split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
  const colorFor=value=>{let n=0;for(const ch of String(value||''))n=(n*31+ch.charCodeAt(0))>>>0;return COLORS[n%COLORS.length]};
  async function api(url,options={}){const r=await fetch(url,options),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.message||'Request failed');return d}
  function clean(text){return String(text||'').replace(/^\s*#{1,6}\s+/gm,'').replace(/\*\*([^*]+)\*\*/g,'$1').replace(/__([^_]+)__/g,'$1').replace(/`([^`]+)`/g,'$1').replace(/^\s*[-*+]\s+/gm,'• ').trim()}

  function nativeLauncher(kind){
    const selectors={activity:'.platform-activity-launch',automation:'.n4-auto,.pa-automation-launch',skills:'.platform-skills-launch',marketplace:'.n4-market'};
    const list=[...document.querySelectorAll(selectors[kind]||'')];
    return list.find(el=>!el.closest('.agentie-connected-profile,.agentie-connected-plugin-tools'))||list[0]||null;
  }
  function invokeNative(kind){const el=nativeLauncher(kind);if(!el)return false;el.click();return true}
  window.__agentieInvokeNativeNavigation=invokeNative;

  function openSettings(){
    document.querySelector('.agentie-settings-overlay')?.remove();
    const overlay=document.createElement('div');overlay.className='agentie-settings-overlay';
    const panel=document.createElement('div');panel.className='agentie-settings-panel';
    panel.innerHTML='<div class="agentie-settings-head"><h3>Settings</h3><button class="agentie-settings-close" type="button">×</button></div><div class="agentie-settings-section"><div class="agentie-settings-label">AI model</div><div data-model-slot></div></div>';
    overlay.appendChild(panel);document.body.appendChild(overlay);
    const close=()=>overlay.remove();panel.querySelector('.agentie-settings-close').onclick=close;overlay.onclick=e=>{if(e.target===overlay)close()};
    window.__agentieMountModelRouter?.(panel.querySelector('[data-model-slot]'));
  }

  function installProfile(){
    const sidebar=document.querySelector('.sidebar'),plugin=document.getElementById('agentiePluginsButton');if(!sidebar||!plugin)return;
    const old=sidebar.querySelector('.agentie-profile-wrap');if(old)old.remove();
    let wrap=sidebar.querySelector('.agentie-connected-profile');
    if(!wrap){
      wrap=document.createElement('div');wrap.className='agentie-connected-profile';
      wrap.innerHTML='<button class="agentie-connected-profile-button" type="button"><span class="agentie-connected-profile-icon">👤</span><span>Profile</span></button><div class="agentie-connected-profile-menu"><button type="button" data-connected-profile="settings">⚙ Settings</button><button type="button" data-connected-profile="activity">◷ Activity</button><button type="button" data-connected-profile="automation">↻ Automation</button></div>';
      sidebar.appendChild(wrap);
      const button=wrap.querySelector('.agentie-connected-profile-button'),menu=wrap.querySelector('.agentie-connected-profile-menu');
      button.onclick=e=>{e.preventDefault();e.stopPropagation();menu.classList.toggle('open')};
      wrap.querySelector('[data-connected-profile="settings"]').onclick=()=>{menu.classList.remove('open');openSettings()};
      wrap.querySelector('[data-connected-profile="activity"]').onclick=()=>{menu.classList.remove('open');invokeNative('activity')};
      wrap.querySelector('[data-connected-profile="automation"]').onclick=()=>{menu.classList.remove('open');invokeNative('automation')};
    }
  }

  function installPluginTools(){
    const panel=document.getElementById('agentiePluginsPanel'),head=panel?.querySelector('.plugins-head');if(!panel||!head)return;
    let tools=panel.querySelector('.agentie-connected-plugin-tools');
    if(!tools){
      tools=document.createElement('div');tools.className='agentie-connected-plugin-tools';
      tools.innerHTML='<div class="agentie-connected-plugin-tools-title">Skills & Marketplace</div><button type="button" data-plugin-tool="skills">⚡ Skills</button><button type="button" data-plugin-tool="marketplace">🧩 Marketplace</button>';
      head.insertAdjacentElement('afterend',tools);
      tools.querySelector('[data-plugin-tool="skills"]').onclick=()=>{panel.classList.remove('open');invokeNative('skills')};
      tools.querySelector('[data-plugin-tool="marketplace"]').onclick=()=>{panel.classList.remove('open');invokeNative('marketplace')};
    }
  }

  function stackFor(d){const stack=document.createElement('div');stack.className='agentie-connected-group-stack';(d.participants||[]).slice(0,3).forEach((name,i)=>{const dot=document.createElement('span');dot.className='agentie-connected-group-dot';dot.style.background=colorFor((d.participant_ids||[])[i]||name);dot.textContent=initials(name).slice(0,1);stack.appendChild(dot)});return stack}
  function markActiveRows(){document.querySelectorAll('#persistentAgentList .sidebar-group-row').forEach(row=>row.classList.toggle('active',!!state.group&&row.dataset.groupId===state.group.id))}
  function renderThread(d){
    if(!state.group||state.group.id!==d.id)return;state.group=d;window.__agentieActiveGroupChat=d;
    const box=document.getElementById('messages');if(!box)return;const nearBottom=(document.documentElement.scrollHeight-window.scrollY-window.innerHeight)<180;box.replaceChildren();
    const head=document.createElement('div');head.className='agentie-connected-group-head';head.appendChild(stackFor(d));const copy=document.createElement('div');copy.className='agentie-connected-group-copy';const strong=document.createElement('strong');strong.textContent=d.name||'Group chat';const small=document.createElement('small');small.textContent=(d.participants||[]).join(' · ');copy.append(strong,small);head.appendChild(copy);box.appendChild(head);
    for(const m of d.messages||[]){const isUser=String(m.sender_type||'')==='user';const row=document.createElement('div');row.className=isUser?'user-row':'assistant-row';const wrap=document.createElement('div');if(!isUser){const author=document.createElement('div');author.className='agentie-connected-group-author';author.textContent=m.sender_name||'Agent';wrap.appendChild(author)}const bubble=document.createElement('div');bubble.className='bubble '+(isUser?'user':'assistant');bubble.textContent=isUser?String(m.message||''):clean(m.message||'');wrap.appendChild(bubble);row.appendChild(wrap);box.appendChild(row)}
    markActiveRows();if(nearBottom)window.scrollTo({top:document.body.scrollHeight,behavior:'auto'});
  }
  function showGroupError(message){const box=document.getElementById('messages');if(!box)return;const row=document.createElement('div');row.className='agentie-connected-group-error';row.textContent=message;box.appendChild(row)}
  async function refreshGroup(){if(!state.group||state.loading)return;state.loading=true;try{const d=await api(`/platform/agent-chats/${encodeURIComponent(state.group.id)}`,{cache:'no-store'});renderThread(d)}catch(e){showGroupError(e.message)}finally{state.loading=false}}
  function leaveGroup(){if(state.poll){clearInterval(state.poll);state.poll=null}state.group=null;window.__agentieActiveGroupChat=null;const input=document.getElementById('messageInput');if(input)input.placeholder='Message Agentie...';markActiveRows()}
  async function openGroup(id){
    if(!id)return;try{window.selectPersistentAgent?.(null)}catch(_){ }
    try{const d=await api(`/platform/agent-chats/${encodeURIComponent(id)}`,{cache:'no-store'});if(state.poll)clearInterval(state.poll);state.group=d;window.__agentieActiveGroupChat=d;renderThread(d);const input=document.getElementById('messageInput');if(input){input.placeholder=`Message ${d.name}...`;input.focus()}state.poll=setInterval(refreshGroup,2200)}catch(e){showGroupError(e.message)}
  }
  async function sendGroup(){
    if(!state.group)return false;const input=document.getElementById('messageInput'),send=document.getElementById('sendButton'),value=String(input?.value||'').trim();if(!value)return true;if(input)input.value='';if(send)send.disabled=true;
    try{await api(`/platform/agent-chats/${encodeURIComponent(state.group.id)}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:value})});await refreshGroup()}catch(e){showGroupError(e.message)}finally{if(send)send.disabled=false;if(input)input.focus()}return true
  }
  window.__agentieOpenGroupChat=openGroup;window.__agentieSendActiveGroupMessage=sendGroup;

  async function loadGroups(){try{const d=await api('/platform/agent-chats',{cache:'no-store'});state.groups=d.items||[];markActiveRows()}catch(_){ }}

  document.addEventListener('click',e=>{
    const groupRow=e.target.closest?.('#persistentAgentList .sidebar-group-row');
    if(groupRow){e.preventDefault();e.stopImmediatePropagation();openGroup(groupRow.dataset.groupId);return}
    const normal=e.target.closest?.('#persistentAgentList .agent-row:not(.sidebar-group-row)');if(normal&&state.group)leaveGroup();
    const atItem=e.target.closest?.('.agentie-at-menu .agentie-at-item');if(atItem){const name=atItem.querySelector('.agentie-at-copy strong')?.textContent?.trim();const group=state.groups.find(x=>x.name===name);if(group){e.preventDefault();e.stopImmediatePropagation();document.querySelector('.agentie-at-menu')?.classList.remove('open');openGroup(group.id)}}
    if(!e.target.closest?.('.agentie-connected-profile'))document.querySelector('.agentie-connected-profile-menu')?.classList.remove('open');
  },true);

  function wireComposer(){
    const send=document.getElementById('sendButton'),input=document.getElementById('messageInput');
    if(send&&!send.dataset.agentieGroupConnected){send.dataset.agentieGroupConnected='1';send.addEventListener('click',e=>{if(!state.group)return;e.preventDefault();e.stopImmediatePropagation();sendGroup()},true)}
    if(input&&!input.dataset.agentieGroupConnected){input.dataset.agentieGroupConnected='1';input.addEventListener('keydown',e=>{if(!state.group)return;if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();e.stopImmediatePropagation();sendGroup()}},true)}
  }

  function install(){installProfile();installPluginTools();wireComposer()}
  let queued=false;new MutationObserver(()=>{if(queued)return;queued=true;requestAnimationFrame(()=>{queued=false;install()})}).observe(document.body,{childList:true,subtree:true});
  setTimeout(()=>{install();loadGroups()},280);setInterval(()=>{install();loadGroups()},2200);
})();
