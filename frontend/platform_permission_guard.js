(()=>{
  if(window.__agentieBuilderRecommendationGuard)return;window.__agentieBuilderRecommendationGuard=true;
  // The base Builder highlights useful recommendations, but recommendations are
  // not grants. On the first review render keep every permission/capability/routine
  // opt-in. The user can then explicitly select what the new agent should receive.
  function guard(){for(const panel of document.querySelectorAll('.platform-panel')){
    const manager=panel.querySelector('[data-manager]'),delegate=panel.querySelector('[data-delegate]');
    if(!manager||panel.dataset.recommendationsOptIn==='1')continue;
    panel.dataset.recommendationsOptIn='1';manager.value='';if(delegate)delegate.checked=false;
    panel.querySelectorAll('[data-option-id]').forEach(x=>x.checked=false);panel.querySelectorAll('[data-routine-index]').forEach(x=>x.checked=false);
    const help=panel.querySelector('.platform-help');if(help&&/proposal/i.test(help.textContent||''))help.textContent+=' Recommendations are opt-in; nothing is granted until you select it.';
  }}
  new MutationObserver(guard).observe(document.body,{childList:true,subtree:true});setTimeout(guard,120);
})();
