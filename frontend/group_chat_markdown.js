(()=>{
  if(window.__agentieGroupChatMarkdown)return;window.__agentieGroupChatMarkdown=true;
  const style=document.createElement('style');style.textContent=`
  .n4-msg-body[data-md-rendered="1"]{white-space:normal}.n4-msg-body[data-md-rendered="1"] p{margin:5px 0}.n4-msg-body[data-md-rendered="1"] h1,.n4-msg-body[data-md-rendered="1"] h2,.n4-msg-body[data-md-rendered="1"] h3,.n4-msg-body[data-md-rendered="1"] h4{font-size:12px;margin:9px 0 4px;font-weight:750}.n4-msg-body[data-md-rendered="1"] ul,.n4-msg-body[data-md-rendered="1"] ol{margin:5px 0 5px 18px;padding:0}.n4-msg-body[data-md-rendered="1"] li{margin:2px 0}.n4-msg-body[data-md-rendered="1"] code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);border:1px solid var(--border);border-radius:5px;padding:1px 4px}.n4-msg-body[data-md-rendered="1"] table{border-collapse:collapse;width:100%;margin:7px 0;font-size:10px}.n4-msg-body[data-md-rendered="1"] th,.n4-msg-body[data-md-rendered="1"] td{border:1px solid var(--border);padding:5px 6px;text-align:left;vertical-align:top}.n4-msg-body[data-md-rendered="1"] th{background:var(--panel)}
  `;document.head.appendChild(style);
  const esc=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const inline=s=>esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/__([^_]+)__/g,'<strong>$1</strong>').replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g,'<em>$1</em>');
  const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
  const divider=line=>cells(line).every(x=>/^:?-{3,}:?$/.test(x));
  function render(md){
    const lines=String(md||'').replace(/\r\n/g,'\n').split('\n'),out=[];let i=0;
    while(i<lines.length){const raw=lines[i],line=raw.trim();if(!line){i++;continue}
      if(line.includes('|')&&i+1<lines.length&&divider(lines[i+1])){const head=cells(raw);i+=2;const rows=[];while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){rows.push(cells(lines[i]));i++}out.push('<table><thead><tr>'+head.map(x=>`<th>${inline(x)}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>`<td>${inline(x)}</td>`).join('')+'</tr>').join('')+'</tbody></table>');continue}
      const h=line.match(/^(#{1,4})\s+(.+)$/);if(h){out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);i++;continue}
      if(/^[-*+]\s+/.test(line)){const items=[];while(i<lines.length&&/^\s*[-*+]\s+/.test(lines[i])){items.push(lines[i].replace(/^\s*[-*+]\s+/,''));i++}out.push('<ul>'+items.map(x=>`<li>${inline(x)}</li>`).join('')+'</ul>');continue}
      if(/^\d+[.)]\s+/.test(line)){const items=[];while(i<lines.length&&/^\s*\d+[.)]\s+/.test(lines[i])){items.push(lines[i].replace(/^\s*\d+[.)]\s+/,''));i++}out.push('<ol>'+items.map(x=>`<li>${inline(x)}</li>`).join('')+'</ol>');continue}
      const para=[raw];i++;while(i<lines.length&&lines[i].trim()&&!/^(#{1,4})\s+/.test(lines[i].trim())&&!/^\s*[-*+]\s+/.test(lines[i])&&!/^\s*\d+[.)]\s+/.test(lines[i])&&!(lines[i].includes('|')&&i+1<lines.length&&divider(lines[i+1]))){para.push(lines[i]);i++}out.push('<p>'+para.map(x=>inline(x.trim())).join('<br>')+'</p>')
    }return out.join('')
  }
  function apply(root=document){root.querySelectorAll?.('.n4-msg-body:not([data-md-rendered])').forEach(el=>{const raw=el.textContent||'';el.innerHTML=render(raw);el.dataset.mdRendered='1'})}
  new MutationObserver(records=>{for(const r of records){for(const n of r.addedNodes){if(n.nodeType===1)apply(n)}}}).observe(document.body,{childList:true,subtree:true});
  apply();
})();

(()=>{
  if(window.__agentieNavigationRewire)return;window.__agentieNavigationRewire=true;
  const style=document.createElement('style');style.textContent=`
    .agentie-profile-menu .agentie-profile-real-action{display:block!important;width:100%!important;margin:0!important;border:0!important;background:transparent!important;color:var(--text)!important;border-radius:8px!important;text-align:left!important;padding:8px 9px!important;font-size:10px!important;cursor:pointer!important}.agentie-profile-menu .agentie-profile-real-action:hover{background:var(--soft)!important}
    .agentie-plugin-tools{display:grid;grid-template-columns:1fr 1fr;gap:7px;padding:10px;margin:0 0 10px;border:1px solid var(--border);border-radius:11px;background:var(--soft)}.agentie-plugin-tools-label{grid-column:1/-1;font-size:9px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:1px}.agentie-plugin-tools .platform-skills-launch,.agentie-plugin-tools .n4-market{display:flex!important;width:100%!important;margin:0!important;align-items:center;justify-content:flex-start;border:1px solid var(--border)!important;background:var(--panel)!important;color:var(--text)!important;border-radius:9px!important;padding:8px 9px!important;font-size:10px!important;cursor:pointer!important}.agentie-plugin-tools .platform-skills-launch:hover,.agentie-plugin-tools .n4-market:hover{background:var(--soft)!important}
    .sidebar>.platform-activity-launch,.sidebar>.pa-automation-launch,.sidebar>.n4-auto,.sidebar>.n4-market,.sidebar>.platform-skills-launch,.sidebar>.platform-chats-launch,.sidebar>.n4-chats{display:none!important}
    .unified-group-head{display:flex;align-items:center;gap:10px;margin:2px 0 18px;padding-bottom:13px;border-bottom:1px solid var(--border)}.unified-group-stack{position:relative;width:42px;height:34px;flex:none}.unified-group-head-dot{position:absolute;width:25px;height:25px;border-radius:50%;border:2px solid var(--panel);display:grid;place-items:center;font-size:7px;font-weight:850;color:#111;box-shadow:0 1px 4px rgba(0,0,0,.16)}.unified-group-head-dot:nth-child(1){left:0;top:5px}.unified-group-head-dot:nth-child(2){left:11px;top:0}.unified-group-head-dot:nth-child(3){left:17px;top:9px}.unified-group-copy strong,.unified-group-copy small{display:block}.unified-group-copy strong{font-size:14px}.unified-group-copy small{font-size:10px;color:var(--muted);margin-top:2px}.unified-group-author{font-size:10px;font-weight:700;color:var(--muted);margin:0 0 3px 2px}.unified-group-error{font-size:11px;color:#ef4444;margin:12px 0}
  `;document.head.appendChild(style);

  const state={group:null,groups:[],poll:null,rewireQueued:false};
  const COLORS=['#ff6b6b','#ffd166','#06d6a0','#4cc9f0','#5e60ce','#c77dff','#f72585','#fb8500'];
  const initials=n=>String(n||'A').split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
  const colorFor=v=>{let n=0;for(const ch of String(v||''))n=(n*31+ch.charCodeAt(0))>>>0;return COLORS[n%COLORS.length]};
  async function api(url,options={}){const r=await fetch(url,options),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.message||'Request failed');return d}
  function clean(text){return String(text||'').replace(/^\s*#{1,6}\s+/gm,'').replace(/\*\*([^*]+)\*\*/g,'$1').replace(/__([^_]+)__/g,'$1').replace(/`([^`]+)`/g,'$1').replace(/^\s*[-*+]\s+/gm,'• ').trim()}

  function realLauncher(selector,container){return container?.querySelector(selector)||document.querySelector(selector)}
  function moveLaunchers(){
    const sidebar=document.querySelector('.sidebar'),profile=document.querySelector('.agentie-profile-menu'),pluginBody=document.querySelector('#agentiePluginsPanel .plugins-body');
    if(profile){
      let activity=profile.querySelector('.platform-activity-launch')||sidebar?.querySelector('.platform-activity-launch');
      if(activity){profile.querySelector('[data-profile-action="activity"]')?.remove();activity.classList.add('agentie-profile-real-action');activity.textContent='◷ Activity';activity.style.removeProperty('display');if(activity.parentElement!==profile)profile.appendChild(activity)}
      let automation=profile.querySelector('.n4-auto,.pa-automation-launch')||sidebar?.querySelector('.n4-auto')||sidebar?.querySelector('.pa-automation-launch');
      if(automation){profile.querySelector('[data-profile-action="automation"]')?.remove();automation.classList.add('agentie-profile-real-action');automation.textContent='↻ Automation';automation.style.removeProperty('display');if(automation.parentElement!==profile)profile.appendChild(automation)}
    }
    if(pluginBody){
      let tools=pluginBody.querySelector('.agentie-plugin-tools');if(!tools){tools=document.createElement('div');tools.className='agentie-plugin-tools';const label=document.createElement('div');label.className='agentie-plugin-tools-label';label.textContent='Skills & marketplace';tools.appendChild(label);pluginBody.prepend(tools)}
      let skills=tools.querySelector('.platform-skills-launch')||sidebar?.querySelector('.platform-skills-launch');
      if(skills){skills.textContent='⚡ Skills';skills.style.removeProperty('display');if(skills.parentElement!==tools)tools.appendChild(skills)}
      let market=tools.querySelector('.n4-market')||sidebar?.querySelector('.n4-market');
      if(market){market.textContent='🧩 Marketplace';market.style.removeProperty('display');if(market.parentElement!==tools)tools.appendChild(market)}
    }
    sidebar?.querySelectorAll('.platform-activity-launch,.pa-automation-launch,.n4-auto,.n4-market,.platform-skills-launch,.platform-chats-launch,.n4-chats').forEach(el=>{el.style.setProperty('display','none','important')});
  }

  function groupStack(d){const stack=document.createElement('div');stack.className='unified-group-stack';(d.participants||[]).slice(0,3).forEach((name,i)=>{const dot=document.createElement('span');dot.className='unified-group-head-dot';dot.style.background=colorFor((d.participant_ids||[])[i]||name);dot.textContent=initials(name).slice(0,1);stack.appendChild(dot)});return stack}
  function renderGroup(d){
    if(!state.group||state.group.id!==d.id)return;state.group=d;window.__agentieActiveGroupChat=d;const box=document.getElementById('messages');if(!box)return;
    const nearBottom=(document.documentElement.scrollHeight-window.scrollY-window.innerHeight)<180;box.replaceChildren();
    const head=document.createElement('div');head.className='unified-group-head';head.appendChild(groupStack(d));const copy=document.createElement('div');copy.className='unified-group-copy';const title=document.createElement('strong');title.textContent=d.name||'Group chat';const sub=document.createElement('small');sub.textContent=(d.participants||[]).join(' · ');copy.append(title,sub);head.appendChild(copy);box.appendChild(head);
    for(const m of d.messages||[]){const isUser=String(m.sender_type||'')==='user';const row=document.createElement('div');row.className=isUser?'user-row':'assistant-row';const wrap=document.createElement('div');if(!isUser){const author=document.createElement('div');author.className='unified-group-author';author.textContent=m.sender_name||'Agent';wrap.appendChild(author)}const bubble=document.createElement('div');bubble.className='bubble '+(isUser?'user':'assistant');bubble.textContent=isUser?String(m.message||''):clean(m.message||'');wrap.appendChild(bubble);row.appendChild(wrap);box.appendChild(row)}
    if(nearBottom)window.scrollTo({top:document.body.scrollHeight,behavior:'auto'});
  }
  function renderGroupError(message){const box=document.getElementById('messages');if(!box)return;const err=document.createElement('div');err.className='unified-group-error';err.textContent=message;box.appendChild(err)}
  async function loadGroups(){try{const d=await api('/platform/agent-chats',{cache:'no-store'});state.groups=d.items||[];syncActiveRows();return state.groups}catch(_){return state.groups}}
  function syncActiveRows(){for(const row of document.querySelectorAll('#persistentAgentList .sidebar-group-row'))row.classList.toggle('active',!!state.group&&row.dataset.groupId===state.group.id)}
  function clearNormalAgentSelection(){const select=document.getElementById('agentType');if(select)select.dispatchEvent(new Event('change',{bubbles:true}))}
  function leaveGroup(){if(state.poll){clearInterval(state.poll);state.poll=null}state.group=null;window.__agentieActiveGroupChat=null;const input=document.getElementById('messageInput');if(input)input.placeholder='Message Agentie...';syncActiveRows()}
  async function refreshGroup(){if(!state.group)return;try{const d=await api(`/platform/agent-chats/${encodeURIComponent(state.group.id)}`,{cache:'no-store'});renderGroup(d)}catch(e){renderGroupError(e.message)}}
  async function openGroup(id){
    if(!id)return;try{clearNormalAgentSelection();const d=await api(`/platform/agent-chats/${encodeURIComponent(id)}`,{cache:'no-store'});if(state.poll)clearInterval(state.poll);state.group=d;window.__agentieActiveGroupChat=d;renderGroup(d);syncActiveRows();const input=document.getElementById('messageInput');if(input){input.placeholder=`Message ${d.name}...`;input.focus()}state.poll=setInterval(refreshGroup,2200)}catch(e){renderGroupError(e.message)}
  }
  async function sendGroup(text){
    if(!state.group)return false;const value=String(text??document.getElementById('messageInput')?.value||'').trim();if(!value)return true;const input=document.getElementById('messageInput'),send=document.getElementById('sendButton');if(input)input.value='';if(send)send.disabled=true;try{await api(`/platform/agent-chats/${encodeURIComponent(state.group.id)}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:value})});await refreshGroup()}catch(e){renderGroupError(e.message)}finally{if(send)send.disabled=false;if(input)input.focus()}return true
  }
  window.__agentieOpenGroupChat=openGroup;window.__agentieSendActiveGroupMessage=sendGroup;

  function interceptGroupNavigation(e){
    const row=e.target.closest?.('#persistentAgentList .sidebar-group-row');if(row){e.preventDefault();e.stopImmediatePropagation();openGroup(row.dataset.groupId);return true}
    const normal=e.target.closest?.('#persistentAgentList .agent-row:not(.sidebar-group-row)');if(normal&&state.group){leaveGroup();return false}
    const item=e.target.closest?.('.agentie-at-menu .agentie-at-item,.agentie-groups-panel .agentie-at-item');if(item){const name=item.querySelector('.agentie-at-copy strong')?.textContent?.trim();const g=state.groups.find(x=>x.name===name);if(g){e.preventDefault();e.stopImmediatePropagation();document.querySelector('.agentie-at-menu')?.classList.remove('open');document.querySelector('.agentie-groups-overlay')?.remove();openGroup(g.id);return true}}
    return false
  }
  document.addEventListener('click',e=>{if(interceptGroupNavigation(e))return;if(!state.group)return;const send=e.target.closest?.('#sendButton');if(send){e.preventDefault();e.stopImmediatePropagation();sendGroup()}},true);
  document.addEventListener('keydown',e=>{if(!state.group||e.target?.id!=='messageInput')return;if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();e.stopImmediatePropagation();sendGroup()}},true);

  function install(){moveLaunchers();syncActiveRows();if(!state.groups.length)loadGroups()}
  new MutationObserver(()=>{if(state.rewireQueued)return;state.rewireQueued=true;requestAnimationFrame(()=>{state.rewireQueued=false;install()})}).observe(document.body,{childList:true,subtree:true});
  setTimeout(()=>{install();loadGroups()},260);setInterval(()=>{moveLaunchers();loadGroups();syncActiveRows()},2400);
})();