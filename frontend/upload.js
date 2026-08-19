(() => {
  const composer = document.querySelector('.composer');
  const messageInput = document.getElementById('messageInput');
  if (!composer || !messageInput) return;

  const style = document.createElement('style');
  style.textContent = `
    .attach-button{border:0;background:transparent;color:var(--muted);font-size:24px;line-height:1;padding:7px 9px;border-radius:10px;cursor:pointer}
    .attach-button:hover{background:var(--soft);color:var(--text)}
    .composer.file-drag{outline:2px dashed var(--success);outline-offset:4px}
    .upload-status{font-size:12px;color:var(--muted);padding:4px 2px}
    .file-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
    .file-actions button,.file-actions a{padding:6px 9px;border:1px solid var(--border);border-radius:9px;background:var(--panel);color:var(--text);cursor:pointer;font-size:12px;text-decoration:none}
    .file-preview{max-height:220px;overflow:auto;margin-top:9px;padding:9px;background:var(--soft);border-radius:10px;font:11px ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;word-break:break-word}
    .file-badge{display:inline-flex;padding:3px 7px;border-radius:999px;background:var(--soft);font-size:11px;color:var(--muted);margin-top:7px}
  `;
  document.head.appendChild(style);

  const picker = document.createElement('input');
  picker.type = 'file';
  picker.multiple = true;
  picker.hidden = true;
  picker.accept = '.pdf,.zip,.csv,.json,.yaml,.yml,.txt,.md,.png,.jpg,.jpeg,.webp,.gif,.bmp,.py,.js,.html,.css,.toml,.ini,.log';
  document.body.appendChild(picker);

  const attach = document.createElement('button');
  attach.type = 'button';
  attach.className = 'attach-button';
  attach.title = 'Attach files';
  attach.setAttribute('aria-label', 'Attach files');
  attach.textContent = '+';
  composer.insertBefore(attach, messageInput);
  attach.addEventListener('click', () => picker.click());
  picker.addEventListener('change', () => uploadFiles([...picker.files]));

  ['dragenter','dragover'].forEach(type => composer.addEventListener(type, event => {
    event.preventDefault(); composer.classList.add('file-drag');
  }));
  ['dragleave','drop'].forEach(type => composer.addEventListener(type, event => {
    event.preventDefault(); composer.classList.remove('file-drag');
  }));
  composer.addEventListener('drop', event => uploadFiles([...event.dataTransfer.files]));

  async function uploadFiles(files) {
    for (const file of files) await uploadOne(file);
    picker.value = '';
  }

  async function uploadOne(file) {
    const row = document.createElement('div');
    row.className = 'assistant-row';
    const status = document.createElement('div');
    status.className = 'upload-status';
    status.textContent = `Uploading ${file.name}…`;
    row.appendChild(status);
    document.getElementById('messages')?.appendChild(row);
    window.scrollTo({top: document.body.scrollHeight, behavior:'smooth'});
    try {
      const body = new FormData(); body.append('file', file, file.name);
      const response = await fetch('/files/upload', {method:'POST', body});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Upload failed');
      row.remove();
      window.addAssistant?.(`Uploaded ${data.card.name}.`, data.card);
    } catch (error) {
      status.textContent = `Upload failed: ${error.message}`;
    }
  }

  const previousRender = window.renderCard;
  window.renderCard = function(card, message) {
    const special = new Set(['uploaded_file','file_text','data_preview','zip_extract']);
    if (!card || !special.has(card.type)) return previousRender(card, message);
    return renderFileResult(card, message);
  };

  function container(title) {
    const wrap = document.createElement('div'); wrap.className = 'card-wrap';
    const card = document.createElement('div'); card.className = 'result-card';
    const heading = document.createElement('div'); heading.className = 'card-title'; heading.textContent = title;
    card.appendChild(heading); wrap.appendChild(card); return [wrap, card];
  }

  function humanBytes(value) {
    let n = Number(value || 0); const units = ['B','KB','MB','GB']; let i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return `${n >= 10 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
  }

  function icon(kind) {
    return ({pdf:'📕',zip:'🗜',image:'🖼',csv:'📊',json:'{}',yaml:'⚙',text:'📄'})[kind] || '📎';
  }

  function addDownloadButton(box, name) {
    const link = document.createElement('a');
    link.textContent = 'Download';
    link.href = `/files/${encodeURIComponent(name)}/download`;
    link.download = name;
    link.setAttribute('aria-label', `Download ${name}`);
    box.appendChild(link);
  }

  function addButton(box, label, name, action) {
    const button = document.createElement('button'); button.textContent = label;
    button.onclick = async () => {
      button.disabled = true; const old = button.textContent; button.textContent = 'Working…';
      try {
        const response = await fetch(`/files/${encodeURIComponent(name)}/action`, {
          method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action})
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'File action failed');
        window.addAssistant?.(data.message || '', data.card || null);
      } catch (error) { window.addAssistant?.(`File action failed: ${error.message}`, null); }
      finally { button.disabled = false; button.textContent = old; }
    };
    box.appendChild(button);
  }

  function renderFileResult(c) {
    if (c.type === 'uploaded_file') {
      const [wrap, el] = container(`${icon(c.kind)} ${c.name}`);
      const meta = document.createElement('div'); meta.className = 'card-meta';
      const details = [humanBytes(c.size_bytes), c.kind || c.suffix || 'file'];
      if (c.pages != null) details.push(`${c.pages} pages`);
      if (c.entries != null) details.push(`${c.entries} files`);
      if (c.width) details.push(`${c.width}×${c.height}`);
      meta.textContent = details.join(' · '); el.appendChild(meta);
      if (c.inspection_error) { const err=document.createElement('div'); err.className='card-meta'; err.textContent=c.inspection_error; el.appendChild(err); }
      const actions = document.createElement('div'); actions.className = 'file-actions';
      addDownloadButton(actions, c.name);
      addButton(actions, 'Inspect', c.name, 'inspect');
      addButton(actions, 'Checksum', c.name, 'checksum');
      if (c.kind === 'zip') addButton(actions, 'Extract', c.name, 'extract');
      if (['pdf','text','csv','json','yaml'].includes(c.kind)) addButton(actions, 'Extract text', c.name, 'text');
      if (['csv','json','yaml'].includes(c.kind)) addButton(actions, 'Preview', c.name, 'preview');
      el.appendChild(actions); return wrap;
    }
    if (c.type === 'file_text') {
      const [wrap, el] = container(`📄 ${c.filename}`);
      const badge=document.createElement('div'); badge.className='file-badge'; badge.textContent=c.truncated?'Text preview · truncated':'Extracted text'; el.appendChild(badge);
      const preview=document.createElement('div'); preview.className='file-preview'; preview.textContent=c.text || ''; el.appendChild(preview); return wrap;
    }
    if (c.type === 'data_preview') {
      const [wrap, el] = container(`📊 ${c.filename}`);
      const preview=document.createElement('div'); preview.className='file-preview';
      preview.textContent = c.rows ? c.rows.map(row=>row.join(' | ')).join('\n') : (c.text || ''); el.appendChild(preview); return wrap;
    }
    if (c.type === 'zip_extract') {
      const [wrap, el] = container(`🗜 Extracted ${c.filename}`);
      const meta=document.createElement('div'); meta.className='card-meta'; meta.textContent=`${c.count} files · ${c.destination}`; el.appendChild(meta);
      const preview=document.createElement('div'); preview.className='file-preview'; preview.textContent=(c.files||[]).slice(0,40).join('\n'); el.appendChild(preview); return wrap;
    }
    return previousRender(c);
  }
})();

// Final response-assembly layer. cards.js intentionally renders only card-backed
// entries in a multi result; hybrid provider output is represented as a text-only
// item, so preserve it here after all other render wrappers have loaded.
(() => {
  const previousRender = window.renderCard;
  if (typeof previousRender !== 'function') return;
  const style = document.createElement('style');
  style.textContent = `.multi-text-result{grid-column:1/-1;width:100%;box-sizing:border-box;padding:14px 16px;border:1px solid var(--border);border-radius:14px;background:var(--panel);white-space:pre-wrap;font-size:14px;line-height:1.55}.routing-info-card{min-height:0!important}.routing-info-card .routing-line{font-size:12px;line-height:1.5}`;
  document.head.appendChild(style);

  const textResult = message => {
    const el = document.createElement('div');
    el.className = 'multi-text-result';
    el.textContent = String(message || '').trim();
    return el;
  };

  const routingInfo = (card, message) => {
    const wrap = document.createElement('div'); wrap.className = 'card-wrap';
    const el = document.createElement('div'); el.className = 'result-card routing-info-card'; wrap.appendChild(el);
    if (message) { const top=document.createElement('div'); top.className='card-topline'; top.textContent=message; el.appendChild(top); }
    const title=document.createElement('div'); title.className='card-title'; title.textContent='⚡ Routing'; el.appendChild(title);
    const line=document.createElement('div'); line.className='routing-line';
    const calls=Number(card.provider_calls||0), provider=card.provider||'model', route=card.route||(calls?'hybrid':'local');
    line.textContent=calls>0?`${route} · ${calls} ${provider} provider call${calls===1?'':'s'}`:`${route} · no ${provider} provider call required`;
    el.appendChild(line); return wrap;
  };

  window.renderCard = function(card, message) {
    if (card && card.type === 'routing_info') return routingInfo(card, message);
    if (card && card.type === 'multi') {
      const grid = previousRender(card, message);
      if (!(grid instanceof HTMLElement)) return grid;
      for (const item of card.items || []) {
        if (!item || item.card) continue;
        const text = String(item.message || '').trim();
        if (text) grid.appendChild(textResult(text));
      }
      return grid;
    }
    return previousRender(card, message);
  };
})();
