(() => {
  const originalRenderCard = window.renderCard;

  const style = document.createElement('style');
  style.textContent = `
    .card-topline{font-size:11px;color:var(--muted);margin-bottom:8px;line-height:1.35}
    .multi-card-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;width:min(720px,calc(100vw - 300px));margin-top:6px}
    .multi-card-grid .card-wrap{width:100%;margin-top:0}
    .multi-card-grid .result-card{height:100%;min-height:135px}
    .multi-card-grid .card-value{font-size:25px;margin:9px 0 5px}
    .multi-card-grid .card-title{font-size:13px}
    @media(max-width:900px){.multi-card-grid{width:min(650px,92vw)}}
    @media(max-width:620px){.multi-card-grid{grid-template-columns:1fr;width:min(330px,92vw)}}
  `;
  document.head.appendChild(style);

  function addTitle(el, text) {
    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = text;
    el.appendChild(title);
  }

  function addMeta(el, text) {
    const meta = document.createElement('div');
    meta.className = 'card-meta';
    meta.textContent = text;
    el.appendChild(meta);
    return meta;
  }

  function listContainer(el) {
    const list = document.createElement('div');
    list.style.display = 'grid';
    list.style.gap = '6px';
    list.style.marginTop = '10px';
    el.appendChild(list);
    return list;
  }

  function row(text, subtext) {
    const item = document.createElement('div');
    item.className = 'metric';
    const main = document.createElement('div');
    main.className = 'metric-value';
    main.style.fontSize = '13px';
    main.textContent = text;
    item.appendChild(main);
    if (subtext) {
      const sub = document.createElement('div');
      sub.className = 'metric-label';
      sub.style.marginTop = '3px';
      sub.style.fontSize = '10px';
      sub.textContent = subtext;
      item.appendChild(sub);
    }
    return item;
  }

  function renderCalculation(el, card) {
    addTitle(el, '🧮 Calculator');
    const value = document.createElement('div');
    value.className = 'card-value';
    value.textContent = String(card.result);
    el.appendChild(value);
    addMeta(el, card.expression || 'Calculation');
  }

  function renderConversion(el, card) {
    addTitle(el, '↔ Unit conversion');
    const value = document.createElement('div');
    value.className = 'card-value';
    value.textContent = `${Number(card.result).toLocaleString(undefined, {maximumFractionDigits: 6})} ${card.to_unit || ''}`;
    el.appendChild(value);
    addMeta(el, `${card.value} ${card.from_unit || ''} → ${card.to_unit || ''}`);
  }

  function renderDateTime(el, card) {
    addTitle(el, '🕒 Local time');
    const date = new Date(card.datetime);
    const value = document.createElement('div');
    value.className = 'card-value';
    value.textContent = date.toLocaleTimeString();
    el.appendChild(value);
    addMeta(el, `${date.toLocaleDateString()} · ${card.timezone || 'local'}`);
  }

  function renderReminder(el, card) {
    addTitle(el, card.repeat_minutes > 0 ? '🔁 Recurring reminder' : '🔔 Reminder');
    const value = document.createElement('div');
    value.className = 'card-value';
    value.style.fontSize = '18px';
    value.textContent = card.text || 'Reminder';
    el.appendChild(value);
    const due = card.due_at ? new Date(card.due_at).toLocaleString() : '—';
    addMeta(el, card.repeat_minutes > 0 ? `Next ${due} · every ${card.repeat_minutes} min` : `Due ${due}`);
  }

  function renderReminders(el, card) {
    addTitle(el, '🔔 Reminders');
    const list = listContainer(el);
    (card.items || []).forEach(item => list.appendChild(row(item.text || 'Reminder', `${item.status || ''} · ${item.due_at ? new Date(item.due_at).toLocaleString() : ''}`)));
    if (!(card.items || []).length) addMeta(el, 'No reminders yet.');
  }

  function renderTasks(el, card) {
    addTitle(el, '✅ Tasks');
    const list = listContainer(el);
    (card.items || []).forEach(item => {
      const done = (item.steps || []).filter(step => step.done).length;
      list.appendChild(row(item.title || item.id, `${item.status || 'pending'} · ${done}/${(item.steps || []).length} steps`));
    });
    if (!(card.items || []).length) addMeta(el, 'No tasks yet.');
  }

  function renderFiles(el, card) {
    addTitle(el, '📄 Workspace files');
    const list = listContainer(el);
    (card.items || []).forEach(item => list.appendChild(row(item.name, `${Math.max(1, Math.round((item.size_bytes || 0) / 1024))} KB · ${item.suffix || 'file'}`)));
    if (!(card.items || []).length) addMeta(el, 'Workspace is empty.');
  }

  function renderApprovals(el, card) {
    addTitle(el, '🛡 Approvals');
    const list = listContainer(el);
    (card.items || []).forEach(item => {
      const box = row(item.action || item.id, item.reason || item.status);
      if (item.status === 'pending') {
        const actions = document.createElement('div');
        actions.className = 'actions';
        const approve = document.createElement('button');
        approve.textContent = 'Approve';
        const deny = document.createElement('button');
        deny.textContent = 'Deny';
        const resolve = async approved => {
          const response = await fetch(`/approvals/${encodeURIComponent(item.id)}/resolve`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approved})});
          if (response.ok) actions.replaceChildren(document.createTextNode(approved ? 'Approved' : 'Denied'));
        };
        approve.addEventListener('click', () => resolve(true));
        deny.addEventListener('click', () => resolve(false));
        actions.append(approve, deny);
        box.appendChild(actions);
      }
      list.appendChild(box);
    });
    if (!(card.items || []).length) addMeta(el, 'No approval requests.');
  }

  function renderSystem(el, card) {
    addTitle(el, '💻 System status');
    const grid = document.createElement('div');
    grid.className = 'grid';
    grid.innerHTML = `<div class="metric"><small>CPU</small>${card.cpu_percent ?? '—'}%</div><div class="metric"><small>Memory</small>${card.memory_percent ?? '—'}%</div><div class="metric"><small>Disk</small>${card.disk_free_gb ?? '—'} GB</div>`;
    el.appendChild(grid);
    addMeta(el, card.hostname || 'Local runtime');
  }

  function renderNote(el, card) {
    addTitle(el, `📝 ${card.title || 'Note'}`);
    const body = document.createElement('div');
    body.style.marginTop = '9px';
    body.style.whiteSpace = 'pre-wrap';
    body.style.fontSize = '13px';
    body.textContent = card.content || '';
    el.appendChild(body);
  }

  function renderStandardExtra(card, message) {
    const wrap = document.createElement('div');
    wrap.className = 'card-wrap';
    const el = document.createElement('div');
    el.className = 'result-card';
    wrap.appendChild(el);
    if (message) {
      const topline = document.createElement('div');
      topline.className = 'card-topline';
      topline.textContent = message;
      el.appendChild(topline);
    }
    if (card.type === 'calculation') renderCalculation(el, card);
    else if (card.type === 'unit_conversion') renderConversion(el, card);
    else if (card.type === 'datetime') renderDateTime(el, card);
    else if (card.type === 'reminder') renderReminder(el, card);
    else if (card.type === 'reminders') renderReminders(el, card);
    else if (card.type === 'tasks') renderTasks(el, card);
    else if (card.type === 'files') renderFiles(el, card);
    else if (card.type === 'approvals') renderApprovals(el, card);
    else if (card.type === 'system') renderSystem(el, card);
    else if (card.type === 'note') renderNote(el, card);
    return wrap;
  }

  window.renderCard = function(card, message) {
    if (card.type === 'multi') {
      const group = document.createElement('div');
      group.className = 'multi-card-grid';
      (card.items || []).forEach(item => {
        if (!item.card) return;
        group.appendChild(window.renderCard(item.card, item.message || ''));
      });
      return group;
    }
    const extra = new Set(['calculation','unit_conversion','datetime','reminder','reminders','tasks','files','approvals','system','note']);
    if (!extra.has(card.type)) return originalRenderCard(card, message);
    return renderStandardExtra(card, message);
  };
})();
