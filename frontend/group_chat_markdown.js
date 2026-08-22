(()=>{
  if(window.__agentieGroupChatMarkdown)return;window.__agentieGroupChatMarkdown=true;
  const style=document.createElement('style');style.textContent=`
  .n4-msg-body[data-md-rendered="1"]{white-space:normal}.n4-msg-body[data-md-rendered="1"] p{margin:5px 0}.n4-msg-body[data-md-rendered="1"] h1,.n4-msg-body[data-md-rendered="1"] h2,.n4-msg-body[data-md-rendered="1"] h3,.n4-msg-body[data-md-rendered="1"] h4{font-size:12px;margin:9px 0 4px;font-weight:750}.n4-msg-body[data-md-rendered="1"] ul,.n4-msg-body[data-md-rendered="1"] ol{margin:5px 0 5px 18px;padding:0}.n4-msg-body[data-md-rendered="1"] li{margin:2px 0}.n4-msg-body[data-md-rendered="1"] code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--panel);border:1px solid var(--border);border-radius:5px;padding:1px 4px}.n4-msg-body[data-md-rendered="1"] table{border-collapse:collapse;width:100%;margin:7px 0;font-size:10px}.n4-msg-body[data-md-rendered="1"] th,.n4-msg-body[data-md-rendered="1"] td{border:1px solid var(--border);padding:5px 6px;text-align:left;vertical-align:top}.n4-msg-body[data-md-rendered="1"] th{background:var(--panel)}
  `;document.head.appendChild(style);
  const esc=s=>String(s??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const inline=s=>esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/__([^_]+)__/g,'<strong>$1</strong>').replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g,'<em>$1</em>');
  const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
  const divider=line=>cells(line).every(x=>/^:?-{3,}:?$/.test(x));
  function render(md){
    const lines=String(md||'').replace(/\r\n/g,'\n').split('\n'),out=[];let i=0;
    while(i<lines.length){const raw=lines[i],line=raw.trim();if(!line){i++;continue}
      if(line.includes('|')&&i+1<lines.length&&divider(lines[i+1])){const head=cells(raw);i+=2;const rows=[];while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){rows.push(cells(lines[i]));i++}out.push('<table><thead><tr>'+head.map(x=>`<th>${inline(x)}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>`<td>${inline(x)}</td>`).join('')+'</tr>').join('')+'</tbody></table>');continue}
      const h=line.match(/^(#{1,4})\s+(.+)$/);if(h){out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);i++;continue}
      if(/^[-*+]\s+/.test(line)){const items=[];while(i<lines.length&&/^\s*[-*+]\s+/.test(lines[i])){items.push(lines[i].replace(/^\s*[-*+]\s+/,''));i++}out.push('<ul>'+items.map(x=>`<li>${inline(x)}</li>`).join('')+'</ul>');continue}
      if(/^\d+[.)]\s+/.test(line)){const items=[];while(i<lines.length&&/^\s*\d+[.)]\s+/.test(lines[i])){items.push(lines[i].replace(/^\s*\d+[.)]\s+/,''));i++}out.push('<ol>'+items.map(x=>`<li>${inline(x)}</li>`).join('')+'</ol>');continue}
      const para=[raw];i++;while(i<lines.length&&lines[i].trim()&&!/^(#{1,4})\s+/.test(lines[i].trim())&&!/^\s*[-*+]\s+/.test(lines[i])&&!/^\s*\d+[.)]\s+/.test(lines[i])&&!(lines[i].includes('|')&&i+1<lines.length&&divider(lines[i+1]))){para.push(lines[i]);i++}out.push('<p>'+para.map(x=>inline(x.trim())).join('<br>')+'</p>')
    }return out.join('')
  }
  function apply(root=document){root.querySelectorAll?.('.n4-msg-body:not([data-md-rendered])').forEach(el=>{const raw=el.textContent||'';el.innerHTML=render(raw);el.dataset.mdRendered='1'})}
  new MutationObserver(records=>{for(const r of records){for(const n of r.addedNodes){if(n.nodeType===1)apply(n)}}}).observe(document.body,{childList:true,subtree:true});
  apply();
})();