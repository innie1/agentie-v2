(()=>{
  if(window.__agentieGroupInstantOpenGuard)return;window.__agentieGroupInstantOpenGuard=true;

  let pending=false;
  let generation=0;
  let observer=null;
  let revealFrame=0;

  function scrollRoot(){
    try{
      const owned=window.__agentieGroupScrollRoot?.();
      if(owned)return owned;
    }catch(_){ }
    const shell=document.querySelector('.chat-shell');
    if(shell){
      const css=getComputedStyle(shell),overflow=String(css.overflowY||css.overflow||'');
      if(/auto|scroll|overlay/.test(overflow))return shell;
    }
    return document.scrollingElement||document.documentElement||document.body;
  }

  function setLatest(root){
    if(!root)return;
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

    const root=scrollRoot();
    const viewport=Number(root?.clientHeight||window.innerHeight||0);
    const retainedHeight=Math.max(Number(messages.scrollHeight||0),viewport);
    messages.style.minHeight=`${retainedHeight}px`;
    messages.style.visibility='hidden';

    observer=new MutationObserver(()=>{
      if(!pending||token!==generation)return;
      if(messages.querySelector('.agentie-connected-group-opening'))return;
      if(!window.__agentieActiveGroupChat)return;
      if(revealFrame)cancelAnimationFrame(revealFrame);
      revealFrame=requestAnimationFrame(()=>finishOpen(messages,token));
    });
    observer.observe(messages,{childList:true,subtree:true});
  }

  // navigation_connect is the only group-chat runtime owner. This guard only
  // prevents a visible top-to-bottom jump while that controller opens a thread.
  window.addEventListener('pointerdown',event=>{
    if(!event.target.closest?.('#persistentAgentList .sidebar-group-row'))return;
    prepareOpen();
  },true);
})();
