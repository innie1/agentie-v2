(()=>{
  if(window.__agentieGroupInstantOpenGuard)return;window.__agentieGroupInstantOpenGuard=true;

  let pending=false;
  let generation=0;
  let observer=null;

  const scrollRoot=()=>document.querySelector('.chat-shell')||document.scrollingElement||document.documentElement;

  function finishOpen(messages,token){
    if(!pending||token!==generation||!messages)return;
    pending=false;
    observer?.disconnect();observer=null;

    const root=scrollRoot();
    if(root){
      const previous=root.style.scrollBehavior;
      root.style.scrollBehavior='auto';
      messages.style.minHeight='';
      root.scrollTop=root.scrollHeight;
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

    // navigation_connect has already swapped in its tiny loading surface during
    // this pointer event. Preserve the real chat container height invisibly so
    // the viewport never collapses upward before the retained thread appears.
    const root=scrollRoot();
    const currentTop=Number(root?.scrollTop||0);
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
  document.addEventListener('pointerdown',event=>{
    if(!event.target.closest?.('#persistentAgentList .sidebar-group-row'))return;
    prepareOpen();
  },true);
})();
