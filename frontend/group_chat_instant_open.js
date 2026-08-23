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
