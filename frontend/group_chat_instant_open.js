(()=>{
  if(window.__agentieGroupInstantOpenGuard)return;window.__agentieGroupInstantOpenGuard=true;

  let pending=false;
  let generation=0;
  let observer=null;

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
    const bottom=Math.max(0,root.scrollHeight-root.clientHeight);
    const isDocument=root===document.scrollingElement||root===document.documentElement||root===document.body;
    if(isDocument){
      root.scrollTop=bottom;
      window.scrollTo({top:bottom,left:0,behavior:'auto'});
    }else root.scrollTop=bottom;
  }

  function finishOpen(messages,token){
    if(!pending||token!==generation||!messages)return;
    pending=false;
    observer?.disconnect();observer=null;

    const root=scrollRoot();
    if(root){
      const previous=root.style.scrollBehavior;
      root.style.scrollBehavior='auto';
      messages.style.minHeight='';
      // Set the real scroll container before revealing the retained thread.
      // MutationObserver callbacks run before paint, so the first visible frame
      // is already positioned at the latest message instead of travelling down.
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

    // This guard listens at window capture, before navigation_connect's
    // document-level group click handler. Preserve the current page height and
    // hide the message surface before that handler swaps in its tiny loader.
    const root=scrollRoot();
    const currentTop=Number(root?.scrollTop||window.scrollY||0);
    const viewport=Number(root?.clientHeight||window.innerHeight||0);
    messages.style.minHeight=`${Math.max(viewport,currentTop+viewport)}px`;
    messages.style.visibility='hidden';

    observer=new MutationObserver(()=>{
      if(!pending||token!==generation)return;
      if(messages.querySelector('.agentie-connected-group-opening'))return;
      if(!window.__agentieActiveGroupChat)return;
      finishOpen(messages,token);
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
