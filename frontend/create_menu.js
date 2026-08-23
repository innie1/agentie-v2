(()=>{
  if(window.__agentieCreateMenu)return;window.__agentieCreateMenu=true;

  const style=document.createElement('style');style.textContent=`
  .agentie-create-menu{position:fixed;z-index:21000;display:none;width:196px;padding:5px;border:1px solid var(--border);border-radius:11px;background:var(--panel);box-shadow:0 16px 45px rgba(0,0,0,.24)}.agentie-create-menu.open{display:grid}.agentie-create-menu button{border:0;background:transparent;color:var(--text);border-radius:8px;padding:10px 11px;text-align:left;font-size:11px;cursor:pointer}.agentie-create-menu button:hover{background:var(--soft)}
  .agentie-create-chat{width:min(760px,100%);display:grid;gap:8px;padding-top:14px!important;padding-bottom:118px!important}.agentie-create-chat .assistant-row,.agentie-create-chat .user-row{margin:0}.agentie-create-prompt{position:relative;margin:2px 0 8px;padding:16px 16px 14px;border-radius:18px;background:color-mix(in srgb,var(--soft) 88%,var(--panel));border:1px solid var(--border)}.agentie-create-prompt h3{margin:0 34px 12px 0;font-size:15px}.agentie-create-dismiss{position:absolute;right:12px;top:10px;border:0;background:transparent;color:var(--muted);font-size:20px;cursor:pointer}.agentie-create-own{width:100%;box-sizing:border-box;margin-top:12px;border:1px solid var(--border);border-radius:10px;background:var(--panel);color:var(--text);padding:11px 12px;outline:0;font-size:12px}.agentie-create-own:focus{border-color:#0b84ff}.agentie-create-actions{display:flex;gap:7px;align-items:center;margin-top:11px}.agentie-create-actions button{border:1px solid var(--border);border-radius:9px;background:var(--panel);color:var(--text);padding:8px 11px;font-size:11px;cursor:pointer}.agentie-create-actions .primary{background:#0b84ff;color:#fff;border-color:#0b84ff}.agentie-create-actions button:disabled{opacity:.5;cursor:default}.agentie-create-hint{font-size:10px;color:var(--muted);line-height:1.45;margin-top:9px}.agentie-create-inline{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:4px 0 8px}.agentie-create-inline button{border:1px solid var(--border);border-radius:9px;background:var(--panel);color:var(--text);padding:7px 10px;font-size:10px;cursor:pointer}.agentie-create-status{font-size:10px;color:var(--muted);margin:5px 0 0}.agentie-create-status.error{color:#ef4444}
  `;document.head.appendChild(style);

  const STARTERS=[
    {label:'Research & find information',detail:'Look things up, compare options, verify facts'},
    {label:'Create, write or build things',detail:'Draft, design, code, prepare or produce work'},
    {label:'Organize, manage or monitor work',detail:'Keep track of work, follow up and coordinate'},
    {label:'Use tools and automate tasks',detail:'Work with connected apps, the browser and routines'},
  ];
  const DEFAULT_NAME='New Agentie';
  let menu=null,flow=null,previousBaseHtml='',previousPlaceholder='';

  const esc=value=>{const d=document.createElement('div');d.textContent=String(value??'');return d.innerHTML};
  async function api(url,options={}){const r=await fetch(url,options),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.message||'Request failed');return d}
  const box=()=>document.getElementById('messages');
  const shell=()=>document.querySelector('.app-shell');
  const composerInput=()=>document.getElementById('messageInput');
  function scrollBottom(){const root=window.__agentieGroupScrollRoot?.()||document.querySelector('.chat-shell')||document.scrollingElement;requestAnimationFrame(()=>{if(root)root.scrollTop=root.scrollHeight})}
  function assistant(text){const row=document.createElement('div');row.className='assistant-row';const bubble=document.createElement('div');bubble.className='bubble assistant';bubble.textContent=text;row.appendChild(bubble);return row}
  function user(text){const row=document.createElement('div');row.className='user-row';const bubble=document.createElement('div');bubble.className='bubble user';bubble.textContent=text;row.appendChild(bubble);return row}
  function setComposerPlaceholder(text){const input=composerInput();if(input)input.placeholder=text}

  function ensureMenu(){
    if(menu)return menu;
    menu=document.createElement('div');menu.className='agentie-create-menu';
    for(const [label,action] of [
      ['Create an Agent',startAgentOnboarding],
      ['Create a Group Chat',openExistingGroupCreator],
      ['Create a Skill',openExistingSkillCreator],
    ]){const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=event=>{event.stopPropagation();closeMenu();action()};menu.appendChild(button)}
    document.body.appendChild(menu);return menu;
  }
  function closeMenu(){menu?.classList.remove('open')}
  function toggleMenu(button){if(!button)return;const el=ensureMenu();if(el.classList.contains('open')){closeMenu();return}const rect=button.getBoundingClientRect();el.classList.add('open');const width=el.getBoundingClientRect().width||196;el.style.left=`${Math.max(8,Math.min(rect.right-width,window.innerWidth-width-8))}px`;el.style.top=`${Math.max(8,Math.min(window.innerHeight-el.offsetHeight-8,rect.bottom+7))}px`}

  function leaveAnyGroup(){if(!window.__agentieActiveGroupChat)return;document.querySelector('#persistentAgentList .agent-row:not(.sidebar-group-row)')?.click()}
  function enterFreshChat(){
    leaveAnyGroup();try{window.selectPersistentAgent?.(null)}catch(_){ }
    const messages=box();if(!messages)return null;
    previousBaseHtml=messages.innerHTML;previousPlaceholder=composerInput()?.placeholder||'';
    messages.replaceChildren();messages.classList.add('agentie-create-chat');shell()?.classList.add('agentie-create-onboarding');
    return messages;
  }
  function finishOnboardingVisuals(){shell()?.classList.remove('agentie-create-onboarding');box()?.classList.remove('agentie-create-chat');setComposerPlaceholder(previousPlaceholder||'Message Agentie')}
  function cancelOnboarding(){
    const messages=box();finishOnboardingVisuals();flow=null;
    try{if(typeof window.restoreChatView==='function')window.restoreChatView(null);else if(messages)messages.innerHTML=previousBaseHtml}catch(_){if(messages)messages.innerHTML=previousBaseHtml}
    composerInput()?.focus()
  }

  function descriptionFrom(custom,selected){const own=String(custom||'').trim();if(own&&selected.length)return `${own}\n\nUseful capability areas: ${selected.join('; ')}.`;if(own)return own;return `Help with these areas: ${selected.join('; ')}.`}
  function selectedLabels(prompt){return [...prompt.querySelectorAll('[data-create-choice]:checked')].map(input=>STARTERS[Number(input.dataset.createChoice)]?.label).filter(Boolean)}

  function startAgentOnboarding(){
    closeMenu();const messages=enterFreshChat();if(!messages)return;
    flow={step:'purpose',messages,description:''};
    messages.appendChild(assistant('Hey, I want to join the team 👋'));
    messages.appendChild(assistant('What would you like me to help with?'));
    const prompt=document.createElement('div');prompt.className='agentie-create-prompt';prompt.innerHTML='<button type="button" class="agentie-create-dismiss" aria-label="Cancel">×</button><h3>What should I help with first?</h3>';
    const list=document.createElement('div');list.className='agentie-choice-list';
    STARTERS.forEach((item,index)=>{const row=document.createElement('label');row.className='agentie-choice-row';row.innerHTML=`<input type="checkbox" data-create-choice="${index}"><span class="agentie-choice-copy"><strong>${esc(item.label)}</strong><small>${esc(item.detail)}</small></span>`;row.querySelector('input').addEventListener('change',event=>row.classList.toggle('selected',event.target.checked));list.appendChild(row)});prompt.appendChild(list);
    const own=document.createElement('input');own.type='text';own.className='agentie-create-own';own.placeholder='Type your own answer';prompt.appendChild(own);
    const status=document.createElement('div');status.className='agentie-create-status';
    const actions=document.createElement('div');actions.className='agentie-create-actions';const next=document.createElement('button');next.type='button';next.className='primary';next.textContent='Continue';next.onclick=()=>continuePurpose(prompt,own,status);actions.appendChild(next);prompt.append(actions,status);prompt.querySelector('.agentie-create-dismiss').onclick=cancelOnboarding;messages.appendChild(prompt);
    setComposerPlaceholder('Describe what you want this agent to do…');composerInput()?.focus();scrollBottom()
  }

  function continuePurpose(prompt,own,status){
    if(!flow||flow.step!=='purpose')return;const selected=selectedLabels(prompt),custom=own.value.trim();if(!selected.length&&!custom){status.classList.add('error');status.textContent='Choose an option or tell me what you need.';return}const description=descriptionFrom(custom,selected);flow.description=description;flow.step='name';prompt.querySelectorAll('input,button').forEach(el=>el.disabled=true);flow.messages.appendChild(user(custom||selected.join(' · ')));askName()
  }

  function askName(){
    if(!flow)return;flow.messages.appendChild(assistant("What's my name?"));const inline=document.createElement('div');inline.className='agentie-create-inline';const fallback=document.createElement('button');fallback.type='button';fallback.textContent='Use New Agentie';fallback.onclick=()=>createFromName(DEFAULT_NAME,inline);inline.appendChild(fallback);flow.messages.appendChild(inline);setComposerPlaceholder('Type my name…');composerInput()?.focus();scrollBottom()
  }

  function autoCapabilityIds(draft,kind){
    const items=kind==='skill'?(draft.skills||[]):(draft.plugins||[]);
    return items.filter(item=>Number(item.score||0)>0&&(kind==='skill'||!!item.installed)).map(item=>String(item.id||'').trim()).filter(Boolean)
  }

  async function createFromName(rawName,statusHost=null){
    if(!flow||flow.step!=='name')return;const name=String(rawName||'').trim()||DEFAULT_NAME;flow.step='creating';flow.messages.appendChild(user(name));const status=document.createElement('div');status.className='agentie-create-status';status.textContent='Joining the team…';(statusHost||flow.messages).appendChild(status);setComposerPlaceholder('Setting up…');
    try{
      const draft=await api('/agent-builder/draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({description:flow.description,name,job:''})});
      const payload={...draft,name:name,job:draft.job||flow.description,skills:autoCapabilityIds(draft,'skill'),plugins:autoCapabilityIds(draft,'plugin'),can_delegate:!!draft.can_delegate_recommended,manager_id:draft.recommended_manager?.id||null};
      const created=await api('/agent-builder/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      finishOnboardingVisuals();flow=null;
      if(typeof window.loadPersistentAgents==='function')await window.loadPersistentAgents();const agent=(window.__agentieAgents||[]).find(item=>String(item.id)===String(created.agent?.id))||created.agent;
      try{window.selectPersistentAgent?.(agent)}catch(_){ }
      const welcome=box()?.querySelector('.assistant-row .bubble.assistant');
      if(welcome&&welcome.textContent.trim().startsWith('Chatting with '))welcome.textContent='Want to put me on a task?';
      else if(!welcome&&typeof window.addAssistant==='function')window.addAssistant('Want to put me on a task?',null);
      composerInput()?.focus();
    }catch(error){flow=flow||{step:'name',messages:box(),description:''};flow.step='name';status.classList.add('error');status.textContent=error?.message||String(error);setComposerPlaceholder('Type my name…');composerInput()?.focus()}
  }

  function submitComposerDuringCreation(){
    if(!flow||flow.step==='creating')return false;const input=composerInput(),value=input?.value.trim();if(!value)return false;input.value='';input.dispatchEvent(new Event('input',{bubbles:true}));
    if(flow.step==='purpose'){const prompt=flow.messages.querySelector('.agentie-create-prompt');const own=prompt?.querySelector('.agentie-create-own');if(own)own.value=value;const status=prompt?.querySelector('.agentie-create-status');continuePurpose(prompt,own,status);return true}
    if(flow.step==='name'){createFromName(value);return true}
    return false
  }

  function openExistingGroupCreator(){if(flow)cancelOnboarding();const launcher=document.querySelector('.n4-chats');if(!launcher){window.agentieNotice?.('⚠️','Group Chat','Group Chat creator is unavailable right now.',null,'create-group-unavailable');return}launcher.click();requestAnimationFrame(()=>setTimeout(()=>{const modals=[...document.querySelectorAll('.n4-modal')],active=modals[modals.length-1],button=[...(active?.querySelectorAll('button')||[])].find(x=>x.textContent.trim()==='New group chat');button?.click()},0))}
  function openExistingSkillCreator(){if(flow)cancelOnboarding();const open=()=>{const button=document.querySelector('.platform-skill-new');if(button){button.click();return true}return false};if(open())return;document.getElementById('agentiePluginsButton')?.click();setTimeout(()=>{if(!open())window.agentieNotice?.('⚠️','Create Skill','Skill creator is unavailable right now.',null,'create-skill-unavailable')},100)}

  window.__agentieStartAgentOnboarding=startAgentOnboarding;
  window.__agentieOpenCreateMenu=button=>toggleMenu(button||document.querySelector('.agent-create'));

  document.addEventListener('click',event=>{if(menu?.classList.contains('open')&&!menu.contains(event.target)&&!event.target.closest?.('.agent-create'))closeMenu()},false);
  document.addEventListener('click',event=>{if(!flow||!event.target.closest?.('#sendButton'))return;if(flow.step==='creating'){event.preventDefault();event.stopImmediatePropagation();return}if(submitComposerDuringCreation()){event.preventDefault();event.stopImmediatePropagation()}},true);
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){closeMenu();return}if(!flow||event.key!=='Enter'||event.shiftKey||event.target!==composerInput())return;if(flow.step==='creating'){event.preventDefault();event.stopImmediatePropagation();return}if(submitComposerDuringCreation()){event.preventDefault();event.stopImmediatePropagation()}},true);
})();