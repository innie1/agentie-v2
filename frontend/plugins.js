(()=>{
  const sidebar=document.querySelector('.sidebar');
  if(!sidebar||document.getElementById('agentiePluginsButton'))return;

  const style=document.createElement('style');
  style.textContent=`
    .sidebar{position:relative;padding-bottom:72px}
    .plugins-launch{position:absolute;left:18px;right:18px;bottom:18px;display:flex;align-items:center;gap:9px;width:calc(100% - 36px);padding:9px 10px;border:1px solid transparent;border-radius:10px;background:transparent;color:var(--text);cursor:pointer;text-align:left}
    .plugins-launch:hover{background:var(--soft);border-color:var(--border)}
    .plugins-launch .plug-dot{width:24px;height:24px;border-radius:8px;display:grid;place-items:center;background:var(--soft);font-size:13px}
    .plugins-panel{position:fixed;left:242px;bottom:18px;width:min(390px,calc(100vw - 270px));max-height:min(620px,78vh);z-index:80;background:var(--panel);border:1px solid var(--border);border-radius:16px;box-shadow:0 18px 55px rgba(0,0,0,.18);overflow:hidden;display:none}
    .plugins-panel.open{display:block}
    .plugins-head{display:flex;align-items:center;justify-content:space-between;padding:15px 16px;border-bottom:1px solid var(--border)}
    .plugins-head strong{font-size:15px}.plugins-close{border:0;background:transparent;color:var(--muted);font-size:20px;cursor:pointer;line-height:1}
    .plugins-body{padding:14px 16px 16px;overflow:auto;max-height:calc(min(620px,78vh) - 54px)}
    .plugins-section{margin-bottom:18px}.plugins-section:last-child{margin-bottom:0}.plugins-section-title{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
    .plugin-empty{font-size:13px;color:var(--muted);padding:10px 0}
    .mcp-row{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px solid var(--border)}.mcp-row:last-child{border-bottom:0}
    .mcp-icon{width:30px;height:30px;border-radius:9px;background:var(--soft);display:grid;place-items:center;flex:none;font-size:13px}
    .mcp-main{min-width:0;flex:1}.mcp-name{font-size:13px;font-weight:650}.mcp-meta{font-size:11px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
    .mcp-inspect{border:1px solid var(--border);background:var(--panel);color:var(--text);padding:5px 8px;border-radius:8px;font-size:11px;cursor:pointer}
    .plugins-foot{display:flex;justify-content:space-between;align-items:center;margin-top:8px;font-size:11px;color:var(--muted)}
    .plugins-refresh{border:0;background:transparent;color:var(--muted);cursor:pointer;padding:3px}
    @media(max-width:760px){.plugins-panel{left:12px;right:12px;bottom:12px;width:auto}.plugins-launch{display:none}}
  `;
  document.head.appendChild(style);

  const button=document.createElement('button');
  button.id='agentiePluginsButton';button.className='plugins-launch';button.type='button';
  button.innerHTML='<span class="plug-dot">🔌</span><span>Plugins</span>';
  sidebar.appendChild(button);

  const panel=document.createElement('div');
  panel.className='plugins-panel';panel.id='agentiePluginsPanel';
  panel.innerHTML=`<div class="plugins-head"><strong>Plugins</strong><button class="plugins-close" type="button" aria-label="Close">×</button></div><div class="plugins-body"><div class="plugin-empty">Loading…</div></div>`;
  document.body.appendChild(panel);
  const body=panel.querySelector('.plugins-body');

  function escPlugin(value){const d=document.createElement('div');d.textContent=String(value??'');return d.innerHTML}
  function sendChat(text){const input=document.getElementById('messageInput'),send=document.getElementById('sendButton');if(!input||!send)return;input.value=text;input.dispatchEvent(new Event('input',{bubbles:true}));send.click();panel.classList.remove('open')}

  async function loadPlugins(){
    body.innerHTML='<div class="plugin-empty">Loading…</div>';
    try{
      const response=await fetch('/plugins/state',{cache:'no-store'});
      if(!response.ok)throw new Error('Could not load plugins');
      const state=await response.json();
      const native=Array.isArray(state.plugins)?state.plugins:[];
      const servers=Array.isArray(state.mcp_servers)?state.mcp_servers:[];
      body.innerHTML=`
        <div class="plugins-section"><div class="plugins-section-title">Installed plugins</div>${native.length?native.map(p=>`<div class="mcp-row"><div class="mcp-icon">◫</div><div class="mcp-main"><div class="mcp-name">${escPlugin(p.name||'Plugin')}</div><div class="mcp-meta">${escPlugin(p.description||'Installed')}</div></div></div>`).join(''):'<div class="plugin-empty">No native plugins installed yet.</div>'}</div>
        <div class="plugins-section"><div class="plugins-section-title">MCP servers</div><div id="agentieMcpRows">${servers.length?servers.map(s=>`<div class="mcp-row"><div class="mcp-icon">${s.transport==='stdio'?'⌘':'↗'}</div><div class="mcp-main"><div class="mcp-name">${escPlugin(s.name)}</div><div class="mcp-meta">${s.transport==='stdio'?'Local · ':'HTTP · '}${escPlugin(s.display||'')}</div></div><button class="mcp-inspect" type="button" data-mcp="${escPlugin(s.name)}">Inspect</button></div>`).join(''):'<div class="plugin-empty">No MCP servers registered.</div>'}</div><div class="plugins-foot"><span>${servers.length} MCP server${servers.length===1?'':'s'}</span><button class="plugins-refresh" type="button">Refresh</button></div></div>`;
      body.querySelectorAll('[data-mcp]').forEach(btn=>btn.addEventListener('click',()=>sendChat(`Inspect MCP ${btn.dataset.mcp}`)));
      const refresh=body.querySelector('.plugins-refresh');if(refresh)refresh.onclick=loadPlugins;
    }catch(error){body.innerHTML=`<div class="plugin-empty">${escPlugin(error.message||'Could not load plugins.')}</div>`}
  }

  button.onclick=()=>{panel.classList.toggle('open');if(panel.classList.contains('open'))loadPlugins()};
  panel.querySelector('.plugins-close').onclick=()=>panel.classList.remove('open');
  document.addEventListener('keydown',event=>{if(event.key==='Escape')panel.classList.remove('open')});
})();
