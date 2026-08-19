(()=>{
  const messages=document.getElementById('messages'),input=document.getElementById('messageInput'),send=document.getElementById('sendButton');
  if(!messages||!input||!send||window.__agentieInlineComputer)return;window.__agentieInlineComputer=true;
  const style=document.createElement('style');
  style.textContent=`
    .inline-computer-row{display:flex;margin:10px 0 14px}.inline-computer{width:min(680px,92vw);border:1px solid var(--border);border-radius:15px;background:var(--panel);overflow:hidden}
    .inline-computer-head{height:42px;display:flex;align-items:center;gap:8px;padding:0 11px 0 13px;border-bottom:1px solid var(--border)}
    .inline-computer-dot{width:8px;height:8px;border-radius:50%;background:#8a8a8a}.inline-computer-dot.active{background:#36a269;box-shadow:0 0 0 3px rgba(54,162,105,.14)}.inline-computer-dot.error{background:#d94a4a}
    .inline-computer-title{font-size:12px;font-weight:700;flex:1}.inline-computer-status{font-size:10px;color:var(--muted);max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .inline-computer-stop{border:1px solid var(--border);border-radius:7px;padding:4px 8px;background:transparent;color:var(--muted);cursor:pointer;font-size:11px}.inline-computer-stop:disabled{opacity:.35;cursor:default}
    .inline-computer-viewport{position:relative;background:#111;aspect-ratio:16/9;overflow:hidden}.inline-computer-viewport img{width:100%;height:100%;display:block;object-fit:contain;background:#111}
    .inline-computer-placeholder{position:absolute;inset:0;display:grid;place-items:center;color:#9b9b9b;font-size:12px;text-align:center;padding:20px}.inline-computer-foot{padding:8px 11px 10px}.inline-computer-url{font-size:10px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.inline-computer-detail{font-size:11px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .web-snapshot-card,.browser-actions-card,.browser-approval-card{width:min(680px,92vw)}.web-snapshot-card img{display:block;width:100%;max-height:520px;object-fit:contain;border-radius:11px;border:1px solid var(--border);background:#111;margin-top:10px}.web-snapshot-url{font-size:10px;color:var(--muted);margin-top:7px;overflow-wrap:anywhere}.web-snapshot-excerpt{font-size:12px;line-height:1.45;margin-top:8px;color:var(--muted)}
    .browser-actions-list{display:grid;gap:6px;margin-top:10px}.browser-action{padding:8px 10px;border-radius:9px;background:var(--soft);font-size:12px}.browser-actions-warning{margin-top:9px;font-size:11px;color:var(--muted)}
    .browser-approval-step{margin-top:10px;padding:10px;border-radius:10px;background:var(--soft);font-size:12px}.browser-approval-actions{display:flex;gap:7px;margin-top:10px}.browser-approval-actions button{border:1px solid var(--border);border-radius:8px;padding:6px 10px;background:var(--panel);color:var(--text);cursor:pointer}.browser-approval-actions .approve{background:var(--accent);color:var(--accent-text);border-color:var(--accent)}
    @media(max-width:760px){.inline-computer,.web-snapshot-card,.browser-actions-card,.browser-approval-card{width:min(100%,92vw)}}
  `;document.head.appendChild(style);

  const browserIntent=text=>/https?:\/\//i.test(text)&&/\b(open|visit|check|inspect|look at|view|screenshot|snapshot|capture|monitor|watch|click|type|fill|search|scroll|press|browse|navigate)\b/i.test(text);
  const continuationIntent=text=>/^\s*(click|type|fill|scroll|press|go back|back|forward|new tab|close tab|screenshot|take a screenshot|search for)\b/i.test(text);

  function computerCard(){
    const row=document.createElement('div');row.className='assistant-row inline-computer-row';row.innerHTML=`<div class="inline-computer"><div class="inline-computer-head"><span class="inline-computer-dot"></span><span class="inline-computer-title">Computer</span><span class="inline-computer-status">Starting</span><button class="inline-computer-stop" type="button">Stop</button></div><div class="inline-computer-viewport"><img alt="Agentie browser view" style="display:none"><div class="inline-computer-placeholder">Starting Agentie's browser…</div></div><div class="inline-computer-foot"><div class="inline-computer-url"></div><div class="inline-computer-detail">Preparing browser task</div></div></div>`;
    return row;
  }
  async function initialState(){try{const r=await fetch('/browser/live/state',{cache:'no-store'});return r.ok?await r.json():{}}catch(_){return {}}}
  async function attachComputer(text){
    if(!(browserIntent(text)||continuationIntent(text)))return;
    const baseline=await initialState(),row=computerCard();
    const working=[...messages.querySelectorAll('.assistant-row')].reverse().find(x=>x.querySelector('.working'));if(working)messages.insertBefore(row,working);else messages.appendChild(row);
    window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'});
    const root=row.querySelector('.inline-computer'),dot=root.querySelector('.inline-computer-dot'),status=root.querySelector('.inline-computer-status'),img=root.querySelector('img'),placeholder=root.querySelector('.inline-computer-placeholder'),url=root.querySelector('.inline-computer-url'),detail=root.querySelector('.inline-computer-detail'),stop=root.querySelector('.inline-computer-stop');
    let lastVersion=Number(baseline.frame_version||0),seenActivity=false,ticks=0,closed=false;
    stop.onclick=async()=>{stop.disabled=true;try{await fetch('/browser/live/stop',{method:'POST'})}catch(_){stop.disabled=false}};
    const timer=setInterval(async()=>{
      if(closed)return;ticks++;
      try{
        const r=await fetch('/browser/live/state',{cache:'no-store'});if(!r.ok)return;const s=await r.json(),version=Number(s.frame_version||0),active=!!s.active;
        const changed=active||version!==Number(baseline.frame_version||0)||String(s.updated_at||'')!==String(baseline.updated_at||'');if(changed)seenActivity=true;
        if(!seenActivity&&ticks<40)return;
        dot.classList.toggle('active',active);dot.classList.toggle('error',s.status==='error');status.textContent=active?(s.status||'Working'):(s.status==='done'?'Done':s.status==='error'?'Error':s.status==='paused'?'Paused':s.status||'Idle');url.textContent=s.url||'';detail.textContent=s.error||s.detail||'';stop.disabled=!active;
        if(version!==lastVersion&&version>0){lastVersion=version;img.src=`/browser/live/frame?v=${version}&t=${Date.now()}`;img.style.display='block';placeholder.style.display='none'}
        if(seenActivity&&!active&&['done','error','paused'].includes(s.status)){closed=true;clearInterval(timer);stop.disabled=true}
      }catch(_){ }
    },450);
    setTimeout(()=>{if(!closed){closed=true;clearInterval(timer);stop.disabled=true}},120000);
  }

  send.addEventListener('click',()=>{const text=input.value.trim();if(text)setTimeout(()=>attachComputer(text),0)},true);
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){const text=input.value.trim();if(text)setTimeout(()=>attachComputer(text),0)}},true);

  function resend(text){if(!text)return;input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));send.click()}
  const previousRender=window.renderCard;
  if(typeof previousRender==='function'){
    window.renderCard=function(card,message){
      if(!card||!['web_snapshot','browser_actions','browser_approval'].includes(card.type))return previousRender(card,message);
      if(card.type==='browser_approval'){
        const wrap=document.createElement('div');wrap.className='card-wrap browser-approval-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
        if(message){const top=document.createElement('div');top.className='card-topline';top.textContent=message;el.appendChild(top)}
        const title=document.createElement('div');title.className='card-title';title.textContent='🛡 Browser approval';el.appendChild(title);
        const u=document.createElement('div');u.className='web-snapshot-url';u.textContent=card.url||'';el.appendChild(u);
        const step=document.createElement('div');step.className='browser-approval-step';step.textContent=card.step||'Consequential browser action';el.appendChild(step);
        const actions=document.createElement('div');actions.className='browser-approval-actions';const approve=document.createElement('button'),deny=document.createElement('button');approve.className='approve';approve.textContent='Approve once';deny.textContent='Deny';actions.append(approve,deny);el.appendChild(actions);
        async function resolve(allowed){approve.disabled=true;deny.disabled=true;try{const r=await fetch(`/approvals/${card.approval.id}/resolve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved:allowed})});if(!r.ok)throw new Error('Could not resolve approval');title.textContent=allowed?'✓ Browser action approved':'Browser action denied';actions.remove();if(allowed)setTimeout(()=>resend(card.command),80)}catch(err){approve.disabled=false;deny.disabled=false;const note=document.createElement('div');note.className='card-meta';note.textContent=err.message;el.appendChild(note)}}
        approve.onclick=()=>resolve(true);deny.onclick=()=>resolve(false);return wrap;
      }
      if(card.type==='browser_actions'){
        const wrap=document.createElement('div');wrap.className='card-wrap browser-actions-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
        if(message){const top=document.createElement('div');top.className='card-topline';top.textContent=message;el.appendChild(top)}
        const title=document.createElement('div');title.className='card-title';title.textContent=`🖥 ${card.title||'Browser actions'}`;el.appendChild(title);
        const u=document.createElement('div');u.className='web-snapshot-url';u.textContent=card.url||'';el.appendChild(u);
        const list=document.createElement('div');list.className='browser-actions-list';(card.actions||[]).forEach(action=>{const row=document.createElement('div');row.className='browser-action';row.textContent=action;list.appendChild(row)});el.appendChild(list);return wrap;
      }
      const wrap=document.createElement('div');wrap.className='card-wrap web-snapshot-card';const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
      if(message){const top=document.createElement('div');top.className='card-topline';top.textContent=message;el.appendChild(top)}
      const title=document.createElement('div');title.className='card-title';title.textContent=`🌐 ${card.title||'Website snapshot'}`;el.appendChild(title);
      const shot=document.createElement('img');shot.src=card.image_url;shot.alt=`Screenshot of ${card.title||card.url||'website'}`;el.appendChild(shot);
      const u=document.createElement('div');u.className='web-snapshot-url';u.textContent=card.url||'';el.appendChild(u);
      const meta=document.createElement('div');meta.className='card-meta';const captured=card.captured_at?new Date(card.captured_at).toLocaleString():'';meta.textContent=`${card.changed?'Changed':'Snapshot'}${captured?' · '+captured:''}`;el.appendChild(meta);
      if(card.excerpt){const ex=document.createElement('div');ex.className='web-snapshot-excerpt';ex.textContent=card.excerpt;el.appendChild(ex)}
      return wrap;
    };
  }
})();
