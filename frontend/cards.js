(() => {
  const originalRenderCard = window.renderCard;

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
    list.style.gap = '8px';
    list.style.marginTop = '14px';
    el.appendChild(list);
    return list;
  }

  function row(text, subtext) {
    const item = document.createElement('div');
    item.className = 'metric';
    const main = document.createElement('div');
    main.className = 'metric-value';
    main.textContent = text;
    item.appendChild(main);
    if (subtext) {
      const sub = document.createElement('div');
      sub.className = 'metric-label';
      sub.style.marginTop = '4px';
      sub.textContent = subtext;
      item.appendChild(sub);
    }
    return item;
  }

  function renderCalculation(el, card) {
    addTitle(el, 'Calculator');
    const value = document.createElement('div');
    value.className = 'card-value';
    value.textContent = String(card.result);
    el.appendChild(value);
    addMeta(el, card.expression || 'Local calculation');
  }

  function renderReminder(el, card) {
    addTitle(el, card.repeat_minutes > 0 ? 'Recurring reminder' : 'Reminder');
    const value = document.createElement('div');
    value.className = 'card-value';
    value.style.fontSize = '24px';
    value.textContent = card.text || 'Reminder';
    el.appendChild(value);
    const due = card.due_at ? new Date(card.due_at).toLocaleString() : '—';
    addMeta(el, card.repeat_minutes > 0 ? `Next: ${due} · repeats every ${card.repeat_minutes} min` : `Due: ${due}`);
  }

  function renderReminders(el, card) {
    addTitle(el, 'Reminders');
    const list = listContainer(el);
    (card.items || []).forEach(item => list.appendChild(row(item.text || 'Reminder', `${item.status || ''} · ${item.due_at ? new Date(item.due_at).toLocaleString() : ''}`)));
    if (!(card.items || []).length) addMeta(el, 'No reminders yet.');
  }

  function renderTasks(el, card) {
    addTitle(el, 'Tasks');
    const list = listContainer(el);
    (card.items || []).forEach(item => {
      const done = (item.steps || []).filter(step => step.done).length;
      list.appendChild(row(item.title || item.id, `${item.status || 'pending'} · ${done}/${(item.steps || []).length} steps`));
    });
    if (!(card.items || []).length) addMeta(el, 'No tasks yet.');
  }

  function renderFiles(el, card) {
    addTitle(el, 'Workspace files');
    const list = listContainer(el);
    (card.items || []).forEach(item => list.appendChild(row(item.name, `${Math.max(1, Math.round((item.size_bytes || 0) / 1024))} KB · ${item.suffix || 'file'}`)));
    if (!(card.items || []).length) addMeta(el, 'Workspace is empty.');
  }

  function renderApprovals(el, card) {
    addTitle(el, 'Approvals');
    const list = listContainer(el);
    (card.items || []).forEach(item => {
      const box = row(item.action || item.id, item.reason || item.status);
      if (item.status === 'pending') {
        const actions = document.createElement('div');
        actions.className = 'card-actions';
        const approve = document.createElement('button');
        approve.textContent = 'Approve';
        const deny = document.createElement('button');
        deny.textContent = 'Deny';
        const resolve = async approved => {
          const response = await fetch(`/approvals/${encodeURIComponent(item.id)}/resolve`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({approved})
          });
          if (response.ok) {
            actions.replaceChildren(document.createTextNode(approved ? 'Approved' : 'Denied'));
          }
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
    addTitle(el, 'System status');
    const grid = document.createElement('div');
    grid.className = 'card-grid';
    grid.innerHTML = `
      <div class="metric"><div class="metric-label">OS</div><div class="metric-value"></div></div>
      <div class="metric"><div class="metric-label">Python</div><div class="metric-value"></div></div>
      <div class="metric"><div class="metric-label">Free disk</div><div class="metric-value"></div></div>`;
    const vals = grid.querySelectorAll('.metric-value');
    vals[0].textContent = card.os || '—';
    vals[1].textContent = card.python || '—';
    vals[2].textContent = `${card.disk_free_gb ?? '—'} GB`;
    el.appendChild(grid);
    addMeta(el, card.hostname || 'Local Agentie runtime');
  }

  function renderNote(el, card) {
    addTitle(el, `Note · ${card.title || ''}`);
    const body = document.createElement('div');
    body.style.marginTop = '12px';
    body.style.whiteSpace = 'pre-wrap';
    body.textContent = card.content || '';
    el.appendChild(body);
  }

  window.renderCard = function(card, message) {
    const extra = new Set(['calculation', 'reminder', 'reminders', 'tasks', 'files', 'approvals', 'system', 'note']);
    if (!extra.has(card.type)) return originalRenderCard(card, message);

    const wrap = document.createElement('div');
    wrap.className = 'card-wrap';
    const el = document.createElement('div');
    el.className = 'result-card';
    wrap.appendChild(el);

    const topline = document.createElement('div');
    topline.className = 'card-topline';
    topline.textContent = message || '';
    el.appendChild(topline);

    if (card.type === 'calculation') renderCalculation(el, card);
    else if (card.type === 'reminder') renderReminder(el, card);
    else if (card.type === 'reminders') renderReminders(el, card);
    else if (card.type === 'tasks') renderTasks(el, card);
    else if (card.type === 'files') renderFiles(el, card);
    else if (card.type === 'approvals') renderApprovals(el, card);
    else if (card.type === 'system') renderSystem(el, card);
    else if (card.type === 'note') renderNote(el, card);
    return wrap;
  };
})();
