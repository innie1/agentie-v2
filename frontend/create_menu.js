(()=>{
  if(window.__agentieCreateMenu)return;window.__agentieCreateMenu=true;

  const style=document.createElement('style');style.textContent=`
    .agentie-create-menu{position:fixed;z-index:21000;display:none;width:190px;padding:5px;border:1px solid var(--border);border-radius:11px;background:var(--panel);box-shadow:0 16px 45px rgba(0,0,0,.24)}.agentie-create-menu.open{display:grid}.agentie-create-menu button{border:0;background:transparent;color:var(--text);border-radius:8px;padding:9px 10px;text-align:left;font-size:11px;cursor:pointer}.agentie-create-menu button:hover{background:var(--soft)}
    .agentie-create-onboarding .composer-wrap{visibility:hidden;pointer-events:none}.agentie-create-chat{width:min(720px,100%);display:grid;gap:12px}.agentie-create-chat .assistant-row,.agentie-create-chat .user-row{margin:0}.agentie-create-card{margin:2px 0 8px;padding:14px;border:1px solid var(--border);border-radius:15px;background:var(--panel)}.agentie-create-card-title{font-size:12px;font-weight:700;margin-bottom:9px}.agentie-create-help{font-size:10px;color:var(--muted);line-height:1.45;margin:6px 0 10px}.agentie-create-options{display:grid;grid-template-columns:1fr 1fr;gap:7px}.agentie-create-option{display:grid;grid-template-columns:18px 1fr;gap:8px;align-items:start;padding:9px;border:1px solid var(--border);border-radius:10px;background:var(--soft);cursor:pointer}.agentie-create-option span{font-size:11px;line-height:1.35}.agentie-create-field{width:100%;box-sizing:border-box;margin-top:10px;border:1px solid var(--border);border-radius:10px;background:var(--soft);color:var(--text);padding:10px;outline:0}.agentie-create-card textarea.agentie-create-field{min-height:82px;resize:vertical}.agentie-create-actions{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.agentie-create-actions button{border:1px solid var(--border);border-radius:9px;background:var(--panel);color:var(--text);padding:8px 11px;font-size:11px;cursor:pointer}.agentie-create-actions button.primary{background:#0b84ff;color:#fff;border-color:#0b84ff}.agentie-create-actions button:disabled{opacity:.5;cursor:default}.agentie-create-status{font-size:10px;color:var(--muted);margin-top:8px}.agentie-create-status.error{color:#ef4444}.agentie-create-review{display:grid;gap:8px}.agentie-create-review-row{padding:9px 10px;border-radius:10px;background:var(--soft)}.agentie-create-review-row strong{display:block;font-size:10px;margin-bottom:3px}.agentie-create-review-row span,.agentie-create-review-row div{font-size:11px;line-height:1.4}.agentie-create-review details{font-size:10px;color:var(--muted)}.agentie-create-review details pre{white-space:pre-wrap;font:10px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--text)}.agentie-create-capabilities{display:grid;gap:6px;margin-top:6px}.agentie-create-capability{display:grid;grid-template-columns:18px 1fr;gap:7px;align-items:start;font-size:10px}.agentie-create-capability small{display:block;color:var(--muted);margin-top:2px}.agentie-create-onboarding .messages{padding-bottom:40px}@media(max-width:680px){.agentie-create-options{grid-template-columns:1fr}}
  `;document.head.appendChild(style);

  const STARTERS=[
    'Research & find information',
    'Create, write or build things',
    'Organize, manage or monitor work',
    'Use tools and automate tasks',
  ];
  const DEFAULT_NAME='New Agentie';
  let menu=null;
  let previousBaseHtml='';

  const esc=value=>{const d=document.createElement('div');d.textContent=String(value??'');return d.innerHTML};
  async function api(url,options={}){const r=await fetch(url,options),d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||d.message||'Request failed');return d}
  function messages(){return document.getElementById('messages')}
  function shell(){return document.querySelector('.app-shell')}
  function scrollBottom(){const root=window.__agentieGroupScrollRoot?.()||document.querySelector('.chat-shell')||document.scrollingElement;requestAnimationFrame(()=>{if(root)root.scrollTop=root.scrollHeight})}
  function assistant(text){const row=document.createElement('div');row.className='assistant-row';const bubble=document.createElement('div');bubble.className='bubble assistant';bubble.textContent=text;row.appendChild(bubble);return row}
  function user(text){const row=document.createElement('div');row.className='user-row';const bubble=document.createElement('div');bubble.className='bubble user';bubble.textContent=text;row.appendChild(bubble);return row}
  function card(){const el=document.createElement('div');el.className='agentie-create-card';return el}
  function actions(...defs){const wrap=document.createElement('div');wrap.className='agentie-create-actions';for(const def of defs){const b=document.createElement('button');b.type='button';b.textContent=def.label;if(def.primary)b.className='primary';b.onclick=def.onClick;wrap.appendChild(b)}return wrap}
  function statusNode(){const s=document.createElement('div');s.className='agentie-create-status';return s}
  function setStatus(node,text,error=false){node.textContent=text||'';node.classList.toggle('error',!!error)}

  function ensureMenu(){
    if(menu)return menu;
    menu=document.createElement('div');menu.className='agentie-create-menu';
    for(const [label,action] of [
      ['Create an Agent',startAgentOnboarding],
      ['Create a Group Chat',openExistingGroupCreator],
      ['Create a Skill',openExistingSkillCreator],
    ]){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=e=>{e.stopPropagation();closeMenu();action()};menu.appendChild(b)}
    document.body.appendChild(menu);return menu;
  }
  function closeMenu(){menu?.classList.remove('open')}
  function toggleMenu(button){if(!button)return;const el=ensureMenu();if(el.classList.contains('open')){closeMenu();return}const rect=button.getBoundingClientRect();el.classList.add('open');const width=el.getBoundingClientRect().width||190;el.style.left=`${Math.max(8,Math.min(rect.right-width,window.innerWidth-width-8))}px`;el.style.top=`${Math.max(8,Math.min(window.innerHeight-el.offsetHeight-8,rect.bottom+7))}px`}

  function leaveAnyGroup(){
    if(!window.__agentieActiveGroupChat)return;
    const normal=document.querySelector('#persistentAgentList .agent-row:not(.sidebar-group-row)');
    if(normal)normal.click();
  }
  function enterFreshChat(){
    const already=!!shell()?.classList.contains('agentie-create-onboarding');
    if(!already){leaveAnyGroup();try{window.selectPersistentAgent?.(null)}catch(_){ }}
    const box=messages();if(!box)return null;
    if(!already)previousBaseHtml=box.innerHTML;
    box.replaceChildren();box.classList.add('agentie-create-chat');shell()?.classList.add('agentie-create-onboarding');
    return box;
  }
  function restoreNormalChat(){
    shell()?.classList.remove('agentie-create-onboarding');
    const box=messages();box?.classList.remove('agentie-create-chat');
    try{if(typeof window.restoreChatView==='function')window.restoreChatView(null);else if(box)box.innerHTML=previousBaseHtml}catch(_){if(box)box.innerHTML=previousBaseHtml}
  }
  function cancelOnboarding(){restoreNormalChat();document.getElementById('messageInput')?.focus()}

  function composeDescription(custom,selected){
    const text=String(custom||'').trim();
    if(text&&selected.length)return `${text}\n\nHelpful capability areas selected by the user: ${selected.join('; ')}.`;
    if(text)return text;
    return `Help with these areas: ${selected.join('; ')}.`;
  }

  function startAgentOnboarding(){
    closeMenu();const box=enterFreshChat();if(!box)return;
    box.appendChild(assistant('Hey, I want to join the team 👋'));
    box.appendChild(assistant('What would you like me to help with? Pick any that fit, or describe something completely different.'));
    const choose=card();choose.dataset.createStep='purpose';
    const title=document.createElement('div');title.className='agentie-create-card-title';title.textContent='What should I help with?';choose.appendChild(title);
    const opts=document.createElement('div');opts.className='agentie-create-options';
    STARTERS.forEach((label,index)=>{const row=document.createElement('label');row.className='agentie-create-option';row.innerHTML=`<input type="checkbox" data-create-starter="${index}"><span>${esc(label)}</span>`;opts.appendChild(row)});choose.appendChild(opts);
    const custom=document.createElement('textarea');custom.className='agentie-create-field';custom.dataset.createCustom='1';custom.placeholder='Or describe any Bot you need...';choose.appendChild(custom);
    const help=document.createElement('div');help.className='agentie-create-help';help.textContent='These are only starting points. They do not lock the Bot into a profession or agent type.';choose.appendChild(help);
    const stat=statusNode();choose.appendChild(actions({label:'Continue',primary:true,onClick:()=>{const selected=[...choose.querySelectorAll('[data-create-starter]:checked')].map(x=>STARTERS[Number(x.dataset.createStarter)]),description=composeDescription(custom.value,selected);if(!custom.value.trim()&&!selected.length){setStatus(stat,'Choose an option or describe the Bot you need.',true);return}choose.querySelectorAll('input,textarea,button').forEach(x=>x.disabled=true);box.appendChild(user(custom.value.trim()||selected.join(' · ')));askName(box,description)}},{label:'Cancel',onClick:cancelOnboarding}));choose.appendChild(stat);box.appendChild(choose);custom.focus();scrollBottom()
  }

  function askName(box,description){
    box.appendChild(assistant("What's my name?"));const naming=card();naming.dataset.createStep='name';
    const input=document.createElement('input');input.className='agentie-create-field';input.dataset.createName='1';input.placeholder=DEFAULT_NAME;naming.appendChild(input);
    const stat=statusNode();const go=async(name)=>{const resolved=String(name||'').trim()||DEFAULT_NAME;naming.querySelectorAll('input,button').forEach(x=>x.disabled=true);box.appendChild(user(resolved));setStatus(stat,'Building my configuration…');try{const draft=await api('/agent-builder/draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({description,name:resolved,job:''})});renderReview(box,draft)}catch(e){naming.querySelectorAll('input,button').forEach(x=>x.disabled=false);setStatus(stat,e.message,true)}};
    naming.appendChild(actions({label:'Continue',primary:true,onClick:()=>go(input.value)},{label:'Use New Agentie',onClick:()=>go(DEFAULT_NAME)},{label:'Start over',onClick:startAgentOnboarding}));naming.appendChild(stat);box.appendChild(naming);input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();go(input.value)}});input.focus();scrollBottom()
  }

  function capabilityRows(items,kind){
    const wrap=document.createElement('div');wrap.className='agentie-create-capabilities';
    for(const item of items||[]){const label=document.createElement('label');label.className='agentie-create-capability';const check=document.createElement('input');check.type='checkbox';check.dataset.createCapability=String(item.id||'');check.dataset.createCapabilityKind=kind;if(kind==='skill')check.checked=Number(item.score||0)>0;else check.checked=Number(item.score||0)>0&&!!item.installed;if(kind==='plugin'&&!item.installed)check.disabled=true;const copy=document.createElement('span');const name=document.createElement('strong');name.textContent=item.name||item.id;const small=document.createElement('small');small.textContent=(item.description||'')+(kind==='plugin'&&!item.installed?' · Connect this plugin first':'');copy.append(name,small);label.append(check,copy);wrap.appendChild(label)}
    return wrap;
  }
  function reviewRow(label,value){const row=document.createElement('div');row.className='agentie-create-review-row';const strong=document.createElement('strong');strong.textContent=label;const body=document.createElement('div');body.textContent=value||'—';row.append(strong,body);return row}

  function renderReview(box,draft){
    box.appendChild(assistant('Here’s the setup I’d use. You can review it before I join the team.'));
    const review=card();review.dataset.createStep='review';const content=document.createElement('div');content.className='agentie-create-review';
    const nameField=document.createElement('input');nameField.className='agentie-create-field';nameField.value=draft.name||DEFAULT_NAME;nameField.dataset.reviewName='1';
    const jobField=document.createElement('input');jobField.className='agentie-create-field';jobField.value=draft.job||'';jobField.dataset.reviewJob='1';
    const identity=document.createElement('div');identity.className='agentie-create-review-row';identity.innerHTML='<strong>Name</strong>';identity.appendChild(nameField);content.appendChild(identity);
    const job=document.createElement('div');job.className='agentie-create-review-row';job.innerHTML='<strong>Job / ownership</strong>';job.appendChild(jobField);content.appendChild(job);
    content.appendChild(reviewRow('Goal',draft.goal));content.appendChild(reviewRow('Working style',draft.working_style));content.appendChild(reviewRow('Responsibilities',(draft.responsibilities||[]).map(x=>`• ${x}`).join('\n')));
    const skillBox=document.createElement('div');skillBox.className='agentie-create-review-row';skillBox.innerHTML='<strong>Recommended Skills</strong>';skillBox.appendChild(capabilityRows(draft.skills,'skill'));content.appendChild(skillBox);
    const pluginBox=document.createElement('div');pluginBox.className='agentie-create-review-row';pluginBox.innerHTML='<strong>Recommended plugins / MCPs</strong>';pluginBox.appendChild(capabilityRows(draft.plugins,'plugin'));content.appendChild(pluginBox);
    if((draft.routine_suggestions||[]).length)content.appendChild(reviewRow('Routine suggestions',(draft.routine_suggestions||[]).map(x=>`${x.trigger} — ${x.action}`).join('\n')));
    content.appendChild(reviewRow('Approval boundaries','Sending, publishing, deleting/overwriting, purchases/payments, transfers, permission changes, production changes and accepting legal terms require approval by default.'));
    const details=document.createElement('details');const summary=document.createElement('summary');summary.textContent='View generated instructions';const pre=document.createElement('pre');pre.textContent=draft.instructions||'';details.append(summary,pre);content.appendChild(details);review.appendChild(content);
    const stat=statusNode();const createButton={label:'Create agent',primary:true,onClick:async()=>{const name=nameField.value.trim()||DEFAULT_NAME,job=jobField.value.trim();if(!job){setStatus(stat,'The generated job is required.',true);return}const selected=[...review.querySelectorAll('[data-create-capability]:checked')],payload={...draft,name,job,skills:selected.filter(x=>x.dataset.createCapabilityKind==='skill').map(x=>x.dataset.createCapability),plugins:selected.filter(x=>x.dataset.createCapabilityKind==='plugin').map(x=>x.dataset.createCapability)};review.querySelectorAll('button,input').forEach(x=>x.disabled=true);setStatus(stat,'Creating…');try{const d=await api('/agent-builder/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});restoreNormalChat();if(typeof window.loadPersistentAgents==='function')await window.loadPersistentAgents();const created=(window.__agentieAgents||[]).find(a=>String(a.id)===String(d.agent?.id))||d.agent;try{window.selectPersistentAgent?.(created)}catch(_){ }if(typeof window.addAssistant==='function'){const connection=(d.connection_needed||[]).length?` Connect ${d.connection_needed.join(', ')} from Plugins when you want me to use them.`:'';window.addAssistant(`I'm ${created?.name||name}. I'm ready to join the team.${connection}`,null)}document.getElementById('messageInput')?.focus()}catch(e){review.querySelectorAll('button,input').forEach(x=>x.disabled=false);setStatus(stat,e.message,true)}}};review.appendChild(actions(createButton,{label:'Start over',onClick:startAgentOnboarding},{label:'Cancel',onClick:cancelOnboarding}));review.appendChild(stat);box.appendChild(review);scrollBottom()
  }

  function openExistingGroupCreator(){
    if(shell()?.classList.contains('agentie-create-onboarding'))restoreNormalChat();const launcher=document.querySelector('.n4-chats');if(!launcher){window.agentieNotice?.('⚠️','Group Chat','Group Chat creator is unavailable right now.',null,'create-group-unavailable');return}launcher.click();requestAnimationFrame(()=>setTimeout(()=>{const modals=[...document.querySelectorAll('.n4-modal')],active=modals[modals.length-1],button=[...(active?.querySelectorAll('button')||[])].find(x=>x.textContent.trim()==='New group chat');if(button)button.click()},0))
  }
  function openExistingSkillCreator(){
    if(shell()?.classList.contains('agentie-create-onboarding'))restoreNormalChat();const open=()=>{const b=document.querySelector('.platform-skill-new');if(b){b.click();return true}return false};if(open())return;document.getElementById('agentiePluginsButton')?.click();setTimeout(()=>{if(!open())window.agentieNotice?.('⚠️','Create Skill','Skill creator is unavailable right now.',null,'create-skill-unavailable')},100)
  }

  window.__agentieStartAgentOnboarding=startAgentOnboarding;
  window.__agentieOpenCreateMenu=()=>toggleMenu(document.querySelector('.agent-create'));

  window.addEventListener('click',event=>{
    const plus=event.target.closest?.('.agent-create');
    if(plus){event.preventDefault();event.stopImmediatePropagation();toggleMenu(plus);return}
    if(menu?.classList.contains('open')&&!menu.contains(event.target))closeMenu();
  },true);
  window.addEventListener('keydown',event=>{if(event.key==='Escape')closeMenu()},true);
})();
