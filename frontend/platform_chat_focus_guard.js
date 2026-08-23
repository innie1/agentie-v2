(()=>{
  if(window.__agentieChatComposerFocusGuard)return;window.__agentieChatComposerFocusGuard=true;
  const states=new WeakMap();
  const isComposer=el=>{
    if(!el?.matches?.('.n4-field textarea'))return false;
    const field=el.closest('.n4-field');
    return String(field?.querySelector('label')?.textContent||'').trim()==='Message or task';
  };
  const stateFor=modal=>{let s=states.get(modal);if(!s){s={focused:false,value:'',start:0,end:0,node:null};states.set(modal,s)}return s};
  const snapshot=ta=>{
    if(!isComposer(ta))return;
    const modal=ta.closest('.n4-modal');if(!modal)return;
    const s=stateFor(modal);s.value=ta.value;s.start=ta.selectionStart??ta.value.length;s.end=ta.selectionEnd??s.start;s.node=ta;
  };
  document.addEventListener('focusin',e=>{
    if(!isComposer(e.target))return;
    const modal=e.target.closest('.n4-modal');if(!modal)return;
    const s=stateFor(modal);s.focused=true;snapshot(e.target);
  },true);
  document.addEventListener('input',e=>snapshot(e.target),true);
  document.addEventListener('keyup',e=>snapshot(e.target),true);
  document.addEventListener('focusout',e=>{
    if(!isComposer(e.target))return;
    const modal=e.target.closest('.n4-modal'),next=e.relatedTarget,s=modal&&states.get(modal);
    if(!s)return;
    // A live DOM replacement normally has no related target. Keep the composer
    // logically focused in that case so the new textarea can take over.
    if(next&&!isComposer(next)&&!next.closest?.('.n4-mention'))s.focused=false;
  },true);
  document.addEventListener('pointerdown',e=>{
    const modal=e.target.closest?.('.n4-modal');if(!modal)return;
    const s=states.get(modal);if(!s?.focused)return;
    if(isComposer(e.target)||e.target.closest?.('.n4-mention'))return;
    s.focused=false;
  },true);
  const restore=modal=>{
    const s=states.get(modal);if(!s?.focused||!modal.isConnected)return;
    const ta=[...modal.querySelectorAll('.n4-field textarea')].find(isComposer);
    if(!ta||ta===s.node)return;
    ta.value=s.value;
    const max=ta.value.length,start=Math.min(Number(s.start)||0,max),end=Math.min(Number(s.end)||start,max);
    s.node=ta;
    requestAnimationFrame(()=>{
      if(!s.focused||!ta.isConnected)return;
      ta.focus({preventScroll:true});
      try{ta.setSelectionRange(start,end)}catch(_){/* textarea may be unavailable during teardown */}
    });
  };
  new MutationObserver(()=>{
    for(const modal of document.querySelectorAll('.n4-modal'))restore(modal);
  }).observe(document.body,{childList:true,subtree:true});
})();
