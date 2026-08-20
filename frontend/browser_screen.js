if(typeof ServiceWorkerGlobalScope!=='undefined'&&self instanceof ServiceWorkerGlobalScope){
  self.addEventListener('install',()=>self.skipWaiting());
  self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
  self.addEventListener('fetch',event=>{
    if(event.request.mode!=='navigate')return;
    event.respondWith(fetch(event.request).then(response=>{
      const headers=new Headers(response.headers);
      headers.set('Cross-Origin-Opener-Policy','same-origin');
      headers.set('Cross-Origin-Embedder-Policy','credentialless');
      headers.set('Permissions-Policy','cross-origin-isolated=*');
      return new Response(response.body,{status:response.status,statusText:response.statusText,headers});
    }));
  });
}else{
(()=>{
  if('serviceWorker'in navigator&&!window.crossOriginIsolated&&!sessionStorage.getItem('agentie-coi-reload')){
    navigator.serviceWorker.register('/browser-screen.js',{scope:'/'}).then(()=>{
      sessionStorage.setItem('agentie-coi-reload','1');
      if(navigator.serviceWorker.controller)location.reload();
      else navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});
    }).catch(()=>{});
  }else if(window.crossOriginIsolated){sessionStorage.removeItem('agentie-coi-reload')}

  if(window.__agentieComputerPanel)return;window.__agentieComputerPanel=true;
  const messages=document.getElementById('messages'),input=document.getElementById('messageInput'),send=document.getElementById('sendButton'),agentType=document.getElementById('agentType');
  const mount=document.getElementById('agentieComputerMount');
  const style=document.createElement('style');style.textContent=`
    .agentie-real-computer{position:relative;width:100%;height:100%;min-height:240px;background:#090b0e;border:1px solid #292d33;border-radius:9px;overflow:hidden;color:#eee}.arc-head{height:34px;display:flex;align-items:center;padding:0 7px 0 10px;background:#111318;border-bottom:1px solid #292d33}.arc-dot{width:7px;height:7px;border-radius:50%;background:#777}.arc-dot.on{background:#28b16f}.arc-title{font-size:10px;font-weight:700;margin-left:7px;flex:1}.arc-status{font-size:9px;color:#8d939d;margin-right:4px}.arc-window-buttons{display:flex;height:100%}.arc-window-buttons button{width:30px;border:0;background:transparent;color:#aaa;cursor:pointer;font-size:12px}.arc-window-buttons button:hover{background:#242830}.arc-window-buttons .arc-close:hover{background:#a92323;color:white}.arc-screen{position:relative;height:calc(100% - 34px);min-height:205px;background:#080b10;overflow:hidden}.arc-frame{position:absolute;left:0;top:0;width:1440px;height:900px;border:0;background:#080b10;transform-origin:0 0}.arc-overlay{position:absolute;inset:0;display:grid;place-items:center;text-align:center;padding:20px;background:#15181d;color:#d8dce2;z-index:2}.arc-overlay.hidden{display:none}.arc-overlay strong{font-size:12px}.arc-overlay p{font-size:10px;color:#858b95;margin:6px 0 0}.arc-spinner{width:19px;height:19px;border:2px solid rgba(255,255,255,.18);border-top-color:#ddd;border-radius:50%;margin:0 auto 9px;animation:arcspin .8s linear infinite}@keyframes arcspin{to{transform:rotate(360deg)}}.agentie-real-computer.minimized{height:34px!important;min-height:34px!important}.agentie-real-computer.minimized .arc-screen{display:none}.arc-screen:fullscreen{width:100vw;height:100vh;background:#000}.arc-screen:fullscreen .arc-frame{position:absolute}
    .browser-actions-card,.browser-approval-card,.web-snapshot-card{width:min(680px,92vw)}.browser-actions-list{display:grid;gap:6px;margin-top:10px}.browser-action{padding:8px 10px;border-radius:9px;background:var(--soft);font-size:12px}
  `;document.head.appendChild(style);

  let root=null,observer=null,desktopUrl='';
  function host(){return mount||messages||document.body}
  function make(){if(root&&root.isConnected)return root;root=document.createElement('div');root.className='agentie-real-computer';root.innerHTML=`<div class="arc-head"><span class="arc-dot"></span><span class="arc-title">Agentie Computer</span><span class="arc-status">Ready</span><div class="arc-window-buttons"><button class="arc-min" type="button" title="Minimize">—</button><button class="arc-max" type="button" title="Fullscreen">□</button><button class="arc-close" type="button" title="Stop">×</button></div></div><div class="arc-screen"><iframe class="arc-frame" title="Agentie Linux desktop" allow="clipboard-read; clipboard-write; fullscreen; cross-origin-isolated" allowfullscreen credentialless tabindex="0"></iframe><div class="arc-overlay"><div><div class="arc-spinner"></div><strong>Agentie Computer</strong><p>Waiting for the Linux desktop…</p></div></div></div>`;const h=host();if(mount)mount.innerHTML='';h.appendChild(root);wire();requestAnimationFrame(fit);return root}
  function fit(){if(!root||root.classList.contains('minimized'))return;const screen=root.querySelector('.arc-screen'),frame=root.querySelector('.arc-frame');if(!screen||!frame)return;const w=screen.clientWidth,h=screen.clientHeight;if(!w||!h)return;const scale=Math.min(w/1440,h/900);frame.style.transform=`scale(${scale})`;frame.style.left=`${Math.max(0,(w-1440*scale)/2)}px`;frame.style.top=`${Math.max(0,(h-900*scale)/2)}px`}
  function state(s,text){make();root.querySelector('.arc-dot').classList.toggle('on',s==='on');root.querySelector('.arc-status').textContent=text||s}
  function overlay(show,title,text){make();const o=root.querySelector('.arc-overlay');o.classList.toggle('hidden',!show);if(show)o.innerHTML=`<div>${title==='Starting'?'<div class="arc-spinner"></div>':''}<strong>${esc(title)}</strong><p>${esc(text||'')}</p></div>`}
  function connect(url){desktopUrl=url;make();const frame=root.querySelector('.arc-frame');const target=url+(url.includes('?')?'&':'?')+'t='+Date.now();if(frame.src!==target)frame.src=target;frame.onload=()=>{overlay(false);state('on','Running');fit();try{frame.focus()}catch(_){}};overlay(false);state('on','Running');setTimeout(fit,100)}
  function wire(){const screen=root.querySelector('.arc-screen');root.querySelector('.arc-min').onclick=()=>{root.classList.toggle('minimized');setTimeout(fit,60)};root.querySelector('.arc-max').onclick=()=>{if(document.fullscreenElement===screen)document.exitFullscreen?.();else screen.requestFullscreen?.().catch(()=>{})};root.querySelector('.arc-close').onclick=async()=>{state('off','Stopping');try{await fetch('/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:'Desktop control: stop',agent_type:agentType?.value||'general'})})}catch(_){}root.querySelector('.arc-frame').src='about:blank';desktopUrl='';state('off','Stopped');overlay(true,'Stopped','The Linux computer is powered down.')};if('ResizeObserver'in window){observer=new ResizeObserver(()=>fit());observer.observe(screen)}document.addEventListener('fullscreenchange',()=>setTimeout(fit,80));document.addEventListener('visibilitychange',()=>{if(!document.hidden)setTimeout(fit,100)})}
  function esc(s){const d=document.createElement('div');d.textContent=String(s??'');return d.innerHTML}
  const computerIntent=t=>/\b(show desktop|start (?:the )?computer|open (?:the )?terminal|file manager|computer files|computer tasks|computer notes)\b/i.test(t)||(/https?:\/\//i.test(t)&&/\b(open|visit|check|inspect|view|screenshot|capture|click|type|fill|scroll|browse|navigate)\b/i.test(t));
  function prepare(text){if(!computerIntent(text))return;make();state('starting','Starting');overlay(true,'Starting','Agentie is preparing the Linux computer.')}
  if(send&&input){send.addEventListener('click',()=>{const t=input.value.trim();if(t)prepare(t)},true);input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){const t=input.value.trim();if(t)prepare(t)}},true)}

  const previousRender=window.renderCard;
  if(typeof previousRender==='function')window.renderCard=function(card,message){
    if(card?.type==='desktop_view'){
      if(card.mode==='wsl'){
        const url=card.kasmvnc_url||card.novnc_url;if(card.running&&url)connect(url);else if(card.app==='stopped'){make();state('off','Stopped');overlay(true,'Stopped','The Linux computer is powered down.')}else if(card.error){make();state('off','Error');overlay(true,'Computer could not start',card.error)}
      }
      const hidden=document.createElement('span');hidden.style.display='none';return hidden
    }
    if(!card||!['browser_actions','browser_approval','web_snapshot'].includes(card.type))return previousRender(card,message);
    const wrap=document.createElement('div');wrap.className='card-wrap '+card.type.replaceAll('_','-')+'-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);const title=document.createElement('div');title.className='card-title';title.textContent=card.type==='browser_approval'?'🛡 Browser approval':card.type==='web_snapshot'?'🌐 '+String(card.title||'Website snapshot'):'🖥 '+String(card.title||'Browser actions');el.appendChild(title);
    if(card.type==='browser_actions'){const list=document.createElement('div');list.className='browser-actions-list';(card.actions||[]).forEach(x=>{const i=document.createElement('div');i.className='browser-action';i.textContent=x;list.appendChild(i)});el.appendChild(list)}
    else if(card.type==='web_snapshot'&&card.image_url){const img=document.createElement('img');img.src=card.image_url;img.alt='Website snapshot';img.style='display:block;width:100%;margin-top:10px;border-radius:10px';el.appendChild(img)}
    else if(card.step){const p=document.createElement('div');p.className='card-meta';p.textContent=card.step;el.appendChild(p)}return wrap
  };
})();
}