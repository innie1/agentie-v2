(()=>{
  if(window.__agentieGroupInstantOpenGuard)return;window.__agentieGroupInstantOpenGuard=true;

  let pending=false;
  let generation=0;
  let observer=null;

  const scrollRoot=()=>document.scrollingElement||document.documentElement;

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

    // The navigation controller has already swapped in its tiny loading view
    // during this same pointer event. Keep enough invisible height to prevent
    // the document from collapsing to the top before the real thread arrives.
    const root=scrollRoot();
    const currentTop=Number(root?.scrollTop||window.scrollY||0);
    messages.style.minHeight=`${Math.max(window.innerHeight,currentTop+window.innerHeight)}px`;
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
