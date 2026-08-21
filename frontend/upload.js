(() => {
  const composer=document.querySelector('.composer');
  const input=document.getElementById('messageInput');
  const send=document.getElementById('sendButton');
  if(!composer||!input||!send)return;

  const style=document.createElement('style');
  style.textContent=`
    .attach-button{border:0!important;background:transparent!important;color:var(--muted)!important;font-size:24px!important;line-height:1;padding:7px 9px!important;border-radius:10px!important;cursor:pointer;flex:0 0 auto}
    .composer.file-drag{outline:2px dashed var(--success);outline-offset:4px}.composer.has-attachments{flex-wrap:wrap}
    .attachment-drafts{display:flex;gap:7px;flex-wrap:wrap;width:100%;padding:1px 2px 5px 46px;order:-1}.attachment-drafts:empty{display:none}
    .attachment-chip{display:grid;grid-template-columns:28px minmax(0,1fr) 22px;gap:7px;align-items:center;max-width:300px;padding:7px 8px;border:1px solid var(--border);border-radius:11px;background:var(--soft);font-size:11px}
    .attachment-chip strong,.attachment-chip small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.attachment-chip small{color:var(--muted);margin-top:2px}.attachment-chip button{padding:0!important;border:0!important;background:transparent!important;color:var(--muted)!important;font-size:16px;cursor:pointer}.attachment-chip.uploading{opacity:.65}.attachment-chip.failed{border-color:#ef4444}
    .file-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.file-actions button,.file-actions a{padding:6px 9px;border:1px solid var(--border);border-radius:9px;background:var(--panel);color:var(--text);cursor:pointer;font-size:12px;text-decoration:none}
    .file-preview{max-height:240px;overflow:auto;margin-top:9px;padding:9px;background:var(--soft);border-radius:10px;font:11px ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;word-break:break-word}.file-badge{display:inline-flex;padding:3px 7px;border-radius:999px;background:var(--soft);font-size:11px;color:var(--muted);margin-top:7px}
    .multi-text-result{grid-column:1/-1;width:100%;box-sizing:border-box;padding:14px 16px;border:1px solid var(--border);border-radius:14px;background:var(--panel);font-size:14px;line-height:1.55}
    .rich-text{line-height:1.62;white-space:normal}.rich-text p{margin:0 0 10px}.rich-text p:last-child{margin-bottom:0}.rich-text h1,.rich-text h2,.rich-text h3{margin:5px 0 9px;line-height:1.3}.rich-text h1{font-size:20px}.rich-text h2{font-size:17px}.rich-text h3{font-size:15px}.rich-text ul,.rich-text ol{margin:5px 0 11px;padding-left:22px}.rich-text li{margin:4px 0}.rich-text strong{font-weight:700}.rich-text em{font-style:italic}.rich-text code{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--soft);padding:2px 5px;border-radius:5px}.rich-text hr{border:0;border-top:1px solid var(--border);margin:13px 0}
  `;
  document.head.appendChild(style);

  const picker=document.createElement('input');
  picker.type='file';picker.multiple=true;picker.hidden=true;
  picker.accept='.pdf,.zip,.csv,.json,.yaml,.yml,.txt,.md,.png,.jpg,.jpeg,.webp,.gif,.bmp,.py,.js,.html,.css,.toml,.ini,.log';
  document.body.appendChild(picker);

  const drafts=document.createElement('div');drafts.className='attachment-drafts';composer.prepend(drafts);
  const attach=document.createElement('button');attach.type='button';attach.className='attach-button';attach.title='Attach files';attach.setAttribute('aria-label','Attach files');attach.textContent='+';composer.insertBefore(attach,input);
  const pending=[];

  const humanBytes=v=>{let n=Number(v||0),i=0,u=['B','KB','MB','GB'];while(n>=1024&&i<u.length-1){n/=1024;i++}return `${n>=10||i===0?Math.round(n):n.toFixed(1)} ${u[i]}`};
  const kindOf=n=>{const e=String(n||'').split('.').pop().toLowerCase();if(e==='pdf')return'pdf';if(e==='zip')return'zip';if(['png','jpg','jpeg','webp','gif','bmp'].includes(e))return'image';if(e==='csv')return'csv';if(e==='json')return'json';if(['yaml','yml'].includes(e))return'yaml';return'text'};
  const icon=k=>({pdf:'📕',zip:'🗜',image:'🖼',csv:'📊',json:'{}',yaml:'⚙',text:'📄'})[k]||'📎';

  function addUser(text){
    const messages=document.getElementById('messages');const row=document.createElement('div');const bubble=document.createElement('div');
    row.className='user-row';bubble.className='bubble user';bubble.textContent=text;row.appendChild(bubble);messages?.appendChild(row);
    window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'});
  }
  function addWorking(){
    const messages=document.getElementById('messages');const row=document.createElement('div');row.className='assistant-row';
    row.innerHTML='<div class="working"><span>Agentie is working</span><span class="working-dots"><span></span><span></span><span></span></span></div>';
    messages?.appendChild(row);window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'});return row;
  }

  function appendInline(parent,text){
    const source=String(text||'');
    const token=/(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_)/g;
    let last=0,m;
    while((m=token.exec(source))){
      if(m.index>last)parent.appendChild(document.createTextNode(source.slice(last,m.index)));
      const raw=m[0];let el;
      if(raw.startsWith('`')){el=document.createElement('code');el.textContent=raw.slice(1,-1)}
      else if(raw.startsWith('**')||raw.startsWith('__')){el=document.createElement('strong');el.textContent=raw.slice(2,-2)}
      else{el=document.createElement('em');el.textContent=raw.slice(1,-1)}
      parent.appendChild(el);last=token.lastIndex;
    }
    if(last<source.length)parent.appendChild(document.createTextNode(source.slice(last)));
  }

  function richText(text){
    const root=document.createElement('div');root.className='rich-text';
    const lines=String(text||'').replace(/\r/g,'').split('\n');
    let list=null,listType='';
    const closeList=()=>{list=null;listType=''};
    for(const rawLine of lines){
      const line=rawLine.trim();
      if(!line){closeList();continue}
      if(/^---+$/.test(line)){closeList();root.appendChild(document.createElement('hr'));continue}
      let m=line.match(/^(#{1,3})\s+(.+)$/);
      if(m){closeList();const h=document.createElement(`h${m[1].length}`);appendInline(h,m[2]);root.appendChild(h);continue}
      m=line.match(/^[-*•]\s+(.+)$/);
      if(m){if(!list||listType!=='ul'){closeList();list=document.createElement('ul');listType='ul';root.appendChild(list)}const li=document.createElement('li');appendInline(li,m[1]);list.appendChild(li);continue}
      m=line.match(/^\d+[.)]\s+(.+)$/);
      if(m){if(!list||listType!=='ol'){closeList();list=document.createElement('ol');listType='ol';root.appendChild(list)}const li=document.createElement('li');appendInline(li,m[1]);list.appendChild(li);continue}
      closeList();const p=document.createElement('p');appendInline(p,line);root.appendChild(p);
    }
    return root;
  }

  function stage(files){
    for(const file of files){
      if(!file)continue;
      if(pending.some(x=>x.file.name===file.name&&x.file.size===file.size&&x.file.lastModified===file.lastModified))continue;
      const item={file,card:null,chip:null};pending.push(item);
      const chip=document.createElement('div');chip.className='attachment-chip';item.chip=chip;
      const ico=document.createElement('div');ico.textContent=icon(kindOf(file.name));ico.style.fontSize='17px';
      const copy=document.createElement('div');const strong=document.createElement('strong');strong.textContent=file.name;const small=document.createElement('small');small.textContent=humanBytes(file.size);copy.append(strong,small);
      const x=document.createElement('button');x.type='button';x.textContent='×';x.title='Remove attachment';x.onclick=()=>{const i=pending.indexOf(item);if(i>=0)pending.splice(i,1);chip.remove();composer.classList.toggle('has-attachments',pending.length>0)};
      chip.append(ico,copy,x);drafts.appendChild(chip);
    }
    composer.classList.toggle('has-attachments',pending.length>0);input.focus();
  }

  attach.onclick=()=>picker.click();picker.onchange=()=>{stage([...picker.files]);picker.value=''};
  ['dragenter','dragover'].forEach(t=>composer.addEventListener(t,e=>{e.preventDefault();composer.classList.add('file-drag')}));
  ['dragleave','drop'].forEach(t=>composer.addEventListener(t,e=>{e.preventDefault();composer.classList.remove('file-drag')}));
  composer.addEventListener('drop',e=>stage([...e.dataTransfer.files]));

  async function upload(item){
    if(item.card)return item.card;
    try{
      const fd=new FormData();fd.append('file',item.file,item.file.name);
      const r=await fetch('/files/upload',{method:'POST',body:fd});const d=await r.json();if(!r.ok)throw Error(d.detail||'Upload failed');
      item.card=d.card;return d.card;
    }catch(err){throw err}
  }

  async function fileAction(name,act){
    const r=await fetch(`/files/${encodeURIComponent(name)}/action`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:act})});
    const d=await r.json();if(!r.ok)throw Error(d.detail||'File action failed');return d;
  }

  async function submitAttachments(){
    if(!pending.length)return;
    const question=input.value.trim();
    const batch=pending.splice(0,pending.length);
    const visible=question||`Attached ${batch.length===1?batch[0].file.name:`${batch.length} files`}`;
    input.value='';drafts.replaceChildren();composer.classList.remove('has-attachments');input.dispatchEvent(new Event('input',{bubbles:true}));addUser(visible);const working=addWorking();input.focus();
    try{
      const cards=[];for(const item of batch)cards.push(await upload(item));
      for(const card of cards)window.addAssistant?.('',card);
      if(question){
        const r=await fetch('/files/reason',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,filenames:cards.map(c=>c.name)})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Attachment reasoning failed');working.remove();window.addAssistant?.(d.message||'I could not produce an answer from that attachment.',null);
      }else{working.remove();window.addAssistant?.('Attachment uploaded. Add a message if you want me to read, summarize, inspect, or analyze it.',null)}
    }catch(err){working.remove();window.addAssistant?.(`Attachment request failed: ${err.message}`,null)}
  }

  send.addEventListener('click',e=>{if(!pending.length)return;e.preventDefault();e.stopImmediatePropagation();submitAttachments()},true);
  input.addEventListener('keydown',e=>{if(!pending.length||e.key!=='Enter'||e.shiftKey)return;e.preventDefault();e.stopImmediatePropagation();submitAttachments()},true);

  const previousRender=window.renderCard;
  function box(title){const w=document.createElement('div');w.className='card-wrap';const el=document.createElement('div');el.className='result-card';const h=document.createElement('div');h.className='card-title';h.textContent=title;el.appendChild(h);w.appendChild(el);return[w,el]}
  function buttonBox(el,c){
    const a=document.createElement('div');a.className='file-actions';
    const dl=document.createElement('a');dl.textContent='Download';dl.href=`/files/${encodeURIComponent(c.name)}/download`;dl.download=c.name;a.appendChild(dl);
    const add=(label,act)=>{const b=document.createElement('button');b.textContent=label;b.onclick=async()=>{const old=b.textContent;b.disabled=true;b.textContent='Working…';try{const d=await fileAction(c.name,act);window.addAssistant?.(d.message||'',d.card||null)}catch(e){window.addAssistant?.(`File action failed: ${e.message}`,null)}finally{b.disabled=false;b.textContent=old}};a.appendChild(b)};
    add('Inspect','inspect');add('Checksum','checksum');if(c.kind==='zip')add('Extract','extract');if(['pdf','text','csv','json','yaml'].includes(c.kind)&&!c.inspection_error)add('Extract text','text');if(['csv','json','yaml'].includes(c.kind))add('Preview','preview');el.appendChild(a);
  }
  function renderFile(c){
    if(c.type==='uploaded_file'){
      const displayName=c.document_name||c.name;const[w,e]=box(`${icon(c.kind)} ${displayName}`);const meta=document.createElement('div');meta.className='card-meta';const p=[];if(c.document_name&&c.document_name!==c.name)p.push(`File: ${c.name}`);p.push(humanBytes(c.size_bytes),c.kind||c.suffix||'file');if(c.pages!=null)p.push(`${c.pages} pages`);if(c.entries!=null)p.push(`${c.entries} files`);meta.textContent=p.join(' · ');e.appendChild(meta);
      if(c.inspection_error){const er=document.createElement('div');er.className='card-meta';er.textContent=`Could not inspect: ${c.inspection_error}`;e.appendChild(er)}buttonBox(e,c);return w;
    }
    if(c.type==='file_text'){const[w,e]=box(`📄 ${c.filename}`);const b=document.createElement('div');b.className='file-badge';b.textContent=c.truncated?'Text preview · truncated':'Extracted text';e.appendChild(b);const p=document.createElement('div');p.className='file-preview';p.textContent=c.text||'';e.appendChild(p);return w}
    if(c.type==='data_preview'){const[w,e]=box(`📊 ${c.filename}`);const p=document.createElement('div');p.className='file-preview';p.textContent=c.rows?c.rows.map(r=>r.join(' | ')).join('\n'):(c.text||'');e.appendChild(p);return w}
    if(c.type==='zip_extract'){const[w,e]=box(`🗜 Extracted ${c.filename}`);const p=document.createElement('div');p.className='file-preview';p.textContent=(c.files||[]).slice(0,50).join('\n');e.appendChild(p);return w}
    return null;
  }
  const textNode=t=>{const e=document.createElement('div');e.className='multi-text-result';e.appendChild(richText(t));return e};
  window.renderCard=function(card,message){
    if(card&&['uploaded_file','file_text','data_preview','zip_extract'].includes(card.type))return renderFile(card);
    if(card&&card.type==='multi'){
      const grid=previousRender(card,message);if(grid instanceof HTMLElement){for(const i of card.items||[]){if(!i||i.card)continue;const t=String(i.message||'').trim();if(t)grid.appendChild(textNode(t))}}return grid;
    }
    return previousRender(card,message);
  };

  const originalAddAssistant=window.addAssistant;
  if(typeof originalAddAssistant==='function'){
    window.addAssistant=function(message,card){
      const text=String(message||'');
      if(!text||card)return originalAddAssistant(message,card);
      const messages=document.getElementById('messages');const row=document.createElement('div');row.className='assistant-row';
      const wrap=document.createElement('div');const bubble=document.createElement('div');bubble.className='bubble assistant';bubble.appendChild(richText(text));wrap.appendChild(bubble);row.appendChild(wrap);messages?.appendChild(row);window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'});
    };
  }
})();