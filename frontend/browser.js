(()=>{
  const previous=window.renderCard;
  if(typeof previous!=='function')return;
  const style=document.createElement('style');
  style.textContent='.web-shot{margin-top:10px;border:1px solid var(--border);border-radius:12px;overflow:hidden;background:var(--soft)}.web-shot img{display:block;width:100%;max-height:520px;object-fit:contain;background:#fff}.web-shot-meta{margin-top:8px;font-size:11px;color:var(--muted);overflow:hidden;text-overflow:ellipsis}.web-shot-excerpt{margin-top:9px;font-size:12px;line-height:1.45;color:var(--muted);white-space:pre-wrap;max-height:120px;overflow:auto}';
  document.head.appendChild(style);
  window.renderCard=function(card,message){
    if(!card||card.type!=='web_snapshot')return previous(card,message);
    const wrap=document.createElement('div');wrap.className='card-wrap';
    const el=document.createElement('div');el.className='result-card';wrap.appendChild(el);
    if(message){const top=document.createElement('div');top.className='card-topline';top.textContent=message;el.appendChild(top)}
    const title=document.createElement('div');title.className='card-title';title.textContent='🌐 '+String(card.title||'Website snapshot');el.appendChild(title);
    const meta=document.createElement('div');meta.className='web-shot-meta';
    const when=card.captured_at?new Date(card.captured_at).toLocaleString():'';
    meta.textContent=String(card.url||'')+' · '+(card.changed?'changed':'no meaningful change')+(when?' · '+when:'');el.appendChild(meta);
    const shot=document.createElement('div');shot.className='web-shot';const img=document.createElement('img');img.src=card.image_url||'';img.alt='Website screenshot';img.loading='lazy';shot.appendChild(img);el.appendChild(shot);
    if(card.excerpt){const excerpt=document.createElement('div');excerpt.className='web-shot-excerpt';excerpt.textContent=String(card.excerpt);el.appendChild(excerpt)}
    return wrap;
  };
})();
