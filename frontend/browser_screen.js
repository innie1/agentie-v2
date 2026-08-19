(()=>{
  if(document.getElementById('agentieComputerPanel'))return;
  const style=document.createElement('style');
  style.textContent=`
    .agentie-computer{position:fixed;right:18px;bottom:18px;width:min(390px,calc(100vw - 36px));z-index:75;background:var(--panel);border:1px solid var(--border);border-radius:15px;box-shadow:0 18px 55px rgba(0,0,0,.22);overflow:hidden;display:none}
    .agentie-computer.visible{display:block}.agentie-computer.collapsed .computer-body{display:none}
    .computer-head{height:42px;display:flex;align-items:center;gap:8px;padding:0 10px 0 12px;border-bottom:1px solid var(--border)}
    .computer-dot{width:8px;height:8px;border-radius:50%;background:#8a8a8a}.computer-dot.active{background:#36a269;box-shadow:0 0 0 3px rgba(54,162,105,.14)}.computer-dot.error{background:#d94a4a}
    .computer-title{font-size:12px;font-weight:700;flex:1}.computer-status{font-size:10px;color:var(--muted);max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .computer-head button{border:0;background:transparent;color:var(--muted);cursor:pointer;padding:4px;font-size:12px}
    .computer-stop{border:1px solid var(--border)!important;border-radius:7px!important;padding:4px 7px!important}.computer-stop:disabled{opacity:.4;cursor:default}
    .computer-viewport{position:relative;background:#111;aspect-ratio:16/10;overflow:hidden}.computer-viewport img{width:100%;height:100%;display:block;object-fit:contain;background:#111}
    .computer-placeholder{position:absolute;inset:0;display:grid;place-items:center;color:#9b9b9b;font-size:12px;text-align:center;padding:20px}
    .computer-foot{padding:8px 10px 10px}.computer-url{font-size:10px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.computer-detail{font-size:11px;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .web-snapshot-card{width:min(680px,92vw)}.web-snapshot-card img{display:block;width:100%;max-height:520px;object-fit:contain;border-radius:11px;border:1px solid var(--border);background:#111;margin-top:10px}.web-snapshot-url{font-size:10px;color:var(--muted);margin-top:7px;overflow-wrap:anywhere}.web-snapshot-excerpt{font-size:12px;line-height:1.45;margin-top:8px;color:var(--muted)}
    @media(max-width:760px){.agentie-computer{right:10px;bottom:10px;width:calc(100vw - 20px)}}
  `;
  document.head.appendChild(style);

  const panel=document.createElement('div');panel.id='agentieComputerPanel';panel.className='agentie-computer';panel.innerHTML=`
    <div class="computer-head"><span class="computer-dot"></span><span class="computer-title">Computer</span><span class="computer-status">Idle</span><button class="computer-stop" type="button">Stop</button><button class="computer-toggle" type="button" aria-label="Collapse">—</button></div>
    <div class="computer-body"><div class="computer-viewport"><img alt="Agentie browser view" style="display:none"><div class="computer-placeholder">Agentie's browser will appear here.</div></div><div class="computer-foot"><div class="computer-url"></div><div class="computer-detail">Waiting for browser activity</div></div></div>`;
  document.body.appendChild(panel);
  const dot=panel.querySelector('.computer-dot'),status=panel.querySelector('.computer-status'),img=panel.querySelector('img'),placeholder=panel.querySelector('.computer-placeholder'),url=panel.querySelector('.computer-url'),detail=panel.querySelector('.computer-detail'),stop=panel.querySelector('.computer-stop'),toggle=panel.querySelector('.computer-toggle');
  let lastVersion=-1,lastActive=false,hideTimer=null;
  toggle.onclick=()=>{panel.classList.toggle('collapsed');toggle.textContent=panel.classList.contains('collapsed')?'□':'—'};
  stop.onclick=async()=>{stop.disabled=true;try{await fetch('/browser/live/stop',{method:'POST'})}catch(_){stop.disabled=false}};

  async function poll(){
    try{
      const r=await fetch('/browser/live/state',{cache:'no-store'});if(!r.ok)return;
      const s=await r.json(),active=!!s.active,version=Number(s.frame_version||0);
      if(active||s.status==='done'||s.status==='error')panel.classList.add('visible');
      dot.classList.toggle('active',active);dot.classList.toggle('error',s.status==='error');
      status.textContent=active?(s.status||'Working'):(s.status==='done'?'Done':s.status==='error'?'Error':'Idle');
      url.textContent=s.url||'';detail.textContent=s.error||s.detail||'';stop.disabled=!active;
      if(version!==lastVersion&&version>0){lastVersion=version;img.src=`/browser/live/frame?v=${version}&t=${Date.now()}`;img.style.display='block';placeholder.style.display='none'}
      if(active){if(hideTimer){clearTimeout(hideTimer);hideTimer=null}panel.classList.remove('collapsed')}
      else if(lastActive&&!hideTimer){hideTimer=setTimeout(()=>{if(!panel.matches(':hover'))panel.classList.add('collapsed')},7000)}
      lastActive=active;
    }catch(_){ }
  }
  setInterval(poll,500);poll();

  const previousRender=window.renderCard;
  if(typeof previousRender==='function'){
    window.renderCard=function(card,message){
      if(!card||card.type!=='web_snapshot')return previousRender(card,message);
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
