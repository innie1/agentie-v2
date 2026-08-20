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
  if('serviceWorker' in navigator&&!window.crossOriginIsolated&&!sessionStorage.getItem('agentie-coi-reload')){
    navigator.serviceWorker.register('/browser-screen.js',{scope:'/'}).then(()=>{
      sessionStorage.setItem('agentie-coi-reload','1');
      if(navigator.serviceWorker.controller)location.reload();
      else navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});
    }).catch(()=>{});
  }else if(window.crossOriginIsolated){sessionStorage.removeItem('agentie-coi-reload')}

  const messages=document.getElementById('messages'),input=document.getElementById('messageInput'),send=document.getElementById('sendButton'),agentType=document.getElementById('agentType');
  if(!messages||!input||!send||window.__agentieRealComputer)return;window.__agentieRealComputer=true;

  const style=document.createElement('style');style.textContent=`
    .agentie-real-row{display:flex;margin:10px 0 14px}.agentie-real-computer{width:min(820px,96vw);border:1px solid var(--border);border-radius:16px;background:var(--panel);overflow:hidden;box-shadow:0 10px 34px rgba(0,0,0,.10)}
    .arc-head{height:44px;display:flex;align-items:center;gap:8px;padding:0 11px;border-bottom:1px solid var(--border)}.arc-dot{width:8px;height:8px;border-radius:50%;background:#888}.arc-dot.on{background:#32a567;box-shadow:0 0 0 3px rgba(50,165,103,.14)}.arc-dot.error{background:#d64b4b}.arc-title{font-size:12px;font-weight:700;flex:1}.arc-status{font-size:10px;color:var(--muted);max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.arc-head button{border:1px solid var(--border);background:transparent;color:var(--text);border-radius:8px;padding:5px 9px;font-size:11px;cursor:pointer}.arc-stop{color:#b54444!important}
    .arc-screen{position:relative;aspect-ratio:16/9;background:#080b10;overflow:hidden}.arc-frame{position:absolute;inset:0;width:100%;height:100%;border:0;background:#080b10}.arc-overlay{position:absolute;inset:0;display:grid;place-items:center;background:linear-gradient(145deg,#121b2a,#1d334d);color:#eef3f8;text-align:center;padding:24px;z-index:2}.arc-overlay.hidden{display:none}.arc-spinner{width:22px;height:22px;border:2px solid rgba(255,255,255,.25);border-top-color:#fff;border-radius:50%;animation:arcspin .8s linear infinite;margin:0 auto 12px}@keyframes arcspin{to{transform:rotate(360deg)}}.arc-overlay strong{font-size:14px}.arc-overlay p{font-size:11px;color:#b9c5d2;line-height:1.45;max-width:520px;margin:7px auto 0}.arc-setup{margin:10px auto 0;max-width:660px;background:rgba(0,0,0,.32);padding:9px 11px;border-radius:9px;font:11px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;text-align:left;user-select:text}.arc-start{margin-top:12px;border:1px solid rgba(255,255,255,.25);background:rgba(255,255,255,.1);color:#fff;border-radius:8px;padding:7px 12px;cursor:pointer}.arc-foot{display:flex;gap:8px;padding:7px 10px;border-top:1px solid var(--border);font-size:10px;color:var(--muted)}.arc-foot .arc-detail{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .browser-actions-card,.browser-approval-card,.web-snapshot-card{width:min(680px,92vw)}.browser-actions-list{display:grid;gap:6px;margin-top:10px}.browser-action{padding:8px 10px;border-radius:9px;background:var(--soft);font-size:12px}.browser-approval-step{margin-top:10px;padding:10px;border-radius:10px;background:var(--soft);font-size:12px}.browser-approval-actions{display:flex;gap:7px;margin-top:10px}.browser-approval-actions button{border:1px solid var(--border);border-radius:8px;padding:6px 10px;background:var(--panel);color:var(--text);cursor:pointer}.browser-approval-actions .approve{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}.web-snapshot-card img{display:block;width:100%;max-height:520px;object-fit:contain;border-radius:11px;border:1px solid var(--border);background:#111;margin-top:10px}.web-snapshot-url{font-size:10px;color:var(--muted);margin-top:7px;overflow-wrap:anywhere}.web-snapshot-excerpt{font-size:12px;line-height:1.45;margin-top:8px;color:var(--muted)}
    @media(max-width:760px){.agentie-real-computer{width:min(100%,96vw)}}`;
  document.head.appendChild(style);

  const computerIntent=t=>/https?:\/\//i.test(t)&&/\b(open|visit|check|inspect|view|screenshot|capture|monitor|watch|click|type|fill|search|scroll|press|browse|navigate)\b/i.test(t)||/^\s*(click|type|fill|scroll|press|go back|back|forward|new tab|close tab|search for)\b/i.test(t)||/\b(show desktop|start (?:the )?computer|open (?:the )?terminal|file manager|computer files|computer tasks|computer notes)\b/i.test(t);
  let row=null,root=null,starting=null,stopped=false;

  function makeComputer(){const r=document.createElement('div');r.className='assistant-row agentie-real-row';r.innerHTML=`<div class="agentie-real-computer"><div class="arc-head"><span class="arc-dot"></span><span class="arc-title">Agentie Computer</span><span class="arc-status">Ready</span><button class="arc-fullscreen" type="button">Fullscreen</button><button class="arc-stop" type="button">Stop</button></div><div class="arc-screen"><iframe class="arc-frame" title="Agentie Linux desktop" allow="clipboard-read; clipboard-write; fullscreen; cross-origin-isolated" allowfullscreen credentialless tabindex="0"></iframe><div class="arc-overlay"><div><div class="arc-spinner"></div><strong>Agentie Computer</strong><p>Waiting for Agentie to start the real Linux desktop…</p></div></div></div><div class="arc-foot"><span class="arc-detail">Persistent Linux desktop · click inside and use your mouse and keyboard</span></div></div>`;return r}
  function place(){if(!row){row=makeComputer();root=row.querySelector('.agentie-real-computer');wire()}if(!row.isConnected)messages.appendChild(row);return root}
  async function agentCall(message){const r=await fetch('/agent/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,agent_type:agentType?.value||'general'})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Computer request failed');return d}
  function setState(state,detail){place();const dot=root.querySelector('.arc-dot'),status=root.querySelector('.arc-status');dot.classList.toggle('on',state==='on');dot.classList.toggle('error',state==='error');status.textContent=state==='on'?'Running':state==='starting'?'Starting':state==='stopped'?'Stopped':state==='error'?'Error':'Ready';if(detail)root.querySelector('.arc-detail').textContent=detail}
  function showOverlay(title,text,setup,withStart=false){place();const o=root.querySelector('.arc-overlay');o.classList.remove('hidden');o.innerHTML=`<div>${title==='Starting'?'<div class="arc-spinner"></div>':'<div style="font-size:30px;margin-bottom:8px">'+(title==='Stopped'?'⏻':'⚠')+'</div>'}<strong>${esc(title)}</strong><p>${esc(text||'')}</p>${setup?`<div class="arc-setup">${esc(setup)}</div>`:''}${withStart?'<button class="arc-start" type="button">Start computer</button>':''}</div>`;const b=o.querySelector('.arc-start');if(b)b.onclick=()=>ensureComputer(true)}
  function connect(url){place();const frame=root.querySelector('.arc-frame');frame.onload=()=>{try{frame.focus()}catch(_){}};frame.src=url+(url.includes('?')?'&':'?')+'t='+Date.now();root.querySelector('.arc-overlay').classList.add('hidden');stopped=false;setState('on','KasmVNC Linux desktop · mouse and keyboard control enabled')}
  async function ensureComputer(force=false){
    place();if(starting)return starting;if(!force&&!stopped&&root.querySelector('.arc-frame').src&&root.querySelector('.arc-overlay').classList.contains('hidden'))return;
    setState('starting','Starting Ubuntu, XFCE, KasmVNC and Chrome');showOverlay('Starting','Agentie is turning on its persistent Linux computer.');
    starting=(async()=>{try{const d=await agentCall('Desktop control: start');const c=d.card||{};if(c.setup_required){stopped=true;setState('error','One-time desktop package setup required');showOverlay('One-time setup required','Agentie could not finish the automatic desktop setup.',c.details||c.setup_command,true);return}const desktopUrl=c.kasmvnc_url||c.novnc_url;if(c.mode==='wsl'&&desktopUrl){connect(desktopUrl);return}throw new Error(d.message||'The WSL desktop did not start.')}catch(e){stopped=true;setState('error',e.message);showOverlay('Computer could not start',e.message,null,true)}finally{starting=null}})();return starting
  }
  async function stopComputer(){place();setState('starting','Stopping the Linux computer');try{await agentCall('Desktop control: stop')}catch(_){}root.querySelector('.arc-frame').src='about:blank';stopped=true;setState('stopped','Agentie Computer is powered down');showOverlay('Stopped','The Linux desktop and Agentie Chrome session are stopped.',null,true)}
  function wire(){root.querySelector('.arc-stop').onclick=stopComputer;root.querySelector('.arc-fullscreen').onclick=()=>{const screen=root.querySelector('.arc-screen');if(screen.requestFullscreen)screen.requestFullscreen().catch(()=>{})}}
  function esc(s){const d=document.createElement('div');d.textContent=String(s??'');return d.innerHTML}

  function prepare(text){if(!computerIntent(text))return;place();setState('starting','Waiting for Agentie computer route');showOverlay('Starting','Agentie is preparing the real Linux computer.');setTimeout(()=>window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'}),0)}
  send.addEventListener('click',()=>{const t=input.value.trim();if(t)prepare(t)},true);input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){const t=input.value.trim();if(t)prepare(t)}},true);

  function resend(text){if(!text)return;input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));send.click()}
  const previousRender=window.renderCard;if(typeof previousRender==='function')window.renderCard=function(card,message){
    if(card?.type==='desktop_view'){
      place();if(card.mode==='wsl'){
        if(card.setup_required){stopped=true;setState('error','One-time setup required');showOverlay('One-time setup required','Agentie could not finish the automatic desktop setup.',card.details||card.setup_command,true)}
        else {const desktopUrl=card.kasmvnc_url||card.novnc_url;if(card.running&&desktopUrl)connect(desktopUrl);
        else if(card.app==='stopped'){stopped=true;root.querySelector('.arc-frame').src='about:blank';setState('stopped','Agentie Computer stopped');showOverlay('Stopped','The Linux desktop is powered down.',null,true)}
        else if(card.error){stopped=true;setState('error',card.error);showOverlay('Computer could not start',card.error,null,true)}}
      }
      const hidden=document.createElement('span');hidden.style.display='none';return hidden
    }
    if(!card||!['browser_actions','browser_approval','web_snapshot'].includes(card.type))return previousRender(card,message);
    if(card.type==='browser_approval'){
      place();const wrap=document.createElement('div');wrap.className='card-wrap browser-approval-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);if(message){const top=document.createElement('div');top.className='card-topline';top.textContent=message;el.appendChild(top)}const title=document.createElement('div');title.className='card-title';title.textContent='🛡 Browser approval';el.appendChild(title);const step=document.createElement('div');step.className='browser-approval-step';step.textContent=card.step||'Consequential browser action';el.appendChild(step);const actions=document.createElement('div');actions.className='browser-approval-actions';const a=document.createElement('button'),d=document.createElement('button');a.className='approve';a.textContent='Approve once';d.textContent='Deny';actions.append(a,d);el.appendChild(actions);async function resolve(ok){a.disabled=d.disabled=true;try{const r=await fetch(`/approvals/${card.approval.id}/resolve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:ok})});if(!r.ok)throw new Error('Could not resolve approval');title.textContent=ok?'✓ Browser action approved':'Browser action denied';actions.remove();if(ok)setTimeout(()=>resend(card.command),80)}catch(_){a.disabled=d.disabled=false}}a.onclick=()=>resolve(true);d.onclick=()=>resolve(false);return wrap
    }
    if(card.type==='browser_actions'){
      place();const wrap=document.createElement('div');wrap.className='card-wrap browser-actions-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);if(message){const top=document.createElement('div');top.className='card-topline';top.textContent=message;el.appendChild(top)}const title=document.createElement('div');title.className='card-title';title.textContent=`🖥 ${card.title||'Browser actions'}`;el.appendChild(title);const list=document.createElement('div');list.className='browser-actions-list';(card.actions||[]).forEach(x=>{const i=document.createElement('div');i.className='browser-action';i.textContent=x;list.appendChild(i)});el.appendChild(list);return wrap
    }
    const wrap=document.createElement('div');wrap.className='card-wrap web-snapshot-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);if(message){const top=document.createElement('div');top.className='card-topline';top.textContent=message;el.appendChild(top)}const title=document.createElement('div');title.className='card-title';title.textContent=`🌐 ${card.title||'Website snapshot'}`;el.appendChild(title);const img=document.createElement('img');img.src=card.image_url;img.alt='Website screenshot';el.appendChild(img);const u=document.createElement('div');u.className='web-snapshot-url';u.textContent=card.url||'';el.appendChild(u);if(card.excerpt){const ex=document.createElement('div');ex.className='web-snapshot-excerpt';ex.textContent=card.excerpt;el.appendChild(ex)}return wrap
  };
})();
}