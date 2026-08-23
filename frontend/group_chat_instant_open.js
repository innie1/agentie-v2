(()=>{
  if(window.__agentieGroupInstantOpenGuard)return;window.__agentieGroupInstantOpenGuard=true;

  let pending=false;
  let generation=0;
  let observer=null;
  let revealFrame=0;

  function scrollRoot(){
    const shell=document.querySelector('.chat-shell');
    if(shell){
      const css=getComputedStyle(shell),overflow=String(css.overflowY||css.overflow||'');
      if(/auto|scroll|overlay/.test(overflow)&&shell.scrollHeight>shell.clientHeight+1)return shell;
    }
    return document.scrollingElement||document.documentElement||document.body;
  }

  function setLatest(root){
    if(!root)return;
    // Direct scrollTop assignment is synchronous and does not animate. Use the
    // full scrollHeight deliberately: browsers clamp it to the maximum bottom.
    root.scrollTop=root.scrollHeight;
  }

  function finishOpen(messages,token){
    if(!pending||token!==generation||!messages)return;
    pending=false;
    observer?.disconnect();observer=null;
    if(revealFrame){cancelAnimationFrame(revealFrame);revealFrame=0}

    const root=scrollRoot();
    if(root){
      const previous=root.style.scrollBehavior;
      root.style.scrollBehavior='auto';
      messages.style.minHeight='';
      // Position at the latest message while the thread is still hidden.
      setLatest(root);
      messages.style.visibility='';
      if(previous)root.style.scrollBehavior=previous;
      else root.style.removeProperty('scroll-behavior');
    }else{
      messages.style.minHeight='';
      messages.style.visibility='';
    }

    const input=document.getElementById('messageInput');
    try{input?.focus({preventScroll:true})}catch(_){ }
  }

  function prepareOpen(){
    const messages=document.getElementById('messages');
    if(!messages)return;
    const token=++generation;
    pending=true;
    observer?.disconnect();
    if(revealFrame){cancelAnimationFrame(revealFrame);revealFrame=0}

    // This guard runs before navigation_connect's document-level group handler.
    // Keep the existing surface height and hide it while the retained thread is
    // swapped in so the page cannot collapse to the top during loading.
    const root=scrollRoot();
    const viewport=Number(root?.clientHeight||window.innerHeight||0);
    const retainedHeight=Math.max(Number(messages.scrollHeight||0),viewport);
    messages.style.minHeight=`${retainedHeight}px`;
    messages.style.visibility='hidden';

    observer=new MutationObserver(()=>{
      if(!pending||token!==generation)return;
      if(messages.querySelector('.agentie-connected-group-opening'))return;
      if(!window.__agentieActiveGroupChat)return;
      // navigation_connect schedules its own bottom positioning with
      // requestAnimationFrame. Register our reveal after that callback so the
      // first visible frame is already at the newest message.
      if(revealFrame)cancelAnimationFrame(revealFrame);
      revealFrame=requestAnimationFrame(()=>finishOpen(messages,token));
    });
    observer.observe(messages,{childList:true,subtree:true});
  }

  // navigation_connect owns the group runtime. This guard only controls the
  // first paint position so opening a group never visibly travels top -> bottom.
  window.addEventListener('pointerdown',event=>{
    if(!event.target.closest?.('#persistentAgentList .sidebar-group-row'))return;
    prepareOpen();
  },true);
})();

(()=>{
  if(window.__agentieGroupAvatarColorGuard)return;window.__agentieGroupAvatarColorGuard=true;
  const COLORS=['#ff6b6b','#ffd166','#06d6a0','#4cc9f0','#5e60ce','#c77dff','#f72585','#fb8500'];
  const initials=name=>String(name||'A').split(/\s+/).slice(0,2).map(x=>x[0]).join('').toUpperCase();
  const colorFor=value=>{let n=0;for(const ch of String(value||''))n=(n*31+ch.charCodeAt(0))>>>0;return COLORS[n%COLORS.length]};

  const style=document.createElement('style');style.textContent=`
    #messages .assistant-row.agentie-connected-group-agent-row{align-items:flex-start;gap:10px}
    #messages .assistant-row.agentie-connected-group-agent-row::before{display:none!important;content:none!important}
    .agentie-connected-group-message-orb{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;flex:none;color:#111;font-size:9px;font-weight:800;box-shadow:inset 0 -5px 10px rgba(0,0,0,.12)}
  `;document.head.appendChild(style);

  function resolveAgent(name){
    const key=String(name||'').trim().toLowerCase();
    return (window.__agentieAgents||[]).find(a=>String(a.name||'').trim().toLowerCase()===key)||null;
  }

  function apply(root=document){
    root.querySelectorAll?.('#messages .assistant-row .agentie-connected-group-author').forEach(author=>{
      const row=author.closest('.assistant-row');
      if(!row||row.querySelector('.agentie-connected-group-message-orb'))return;
      const name=String(author.textContent||'Agent').trim();
      const agent=resolveAgent(name);
      const orb=document.createElement('span');
      orb.className='agentie-connected-group-message-orb';
      orb.dataset.agentId=String(agent?.id||'');
      orb.style.background=colorFor(agent?.id||name);
      orb.textContent=initials(agent?.name||name).slice(0,2);
      row.classList.add('agentie-connected-group-agent-row');
      row.prepend(orb);
    });
  }

  new MutationObserver(records=>{for(const record of records){for(const node of record.addedNodes){if(node.nodeType===1)apply(node)}}}).observe(document.body,{childList:true,subtree:true});
  apply();
})();
