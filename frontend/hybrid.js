(() => {
  const previousRenderCard = window.renderCard;
  if (typeof previousRenderCard !== 'function') return;

  const style = document.createElement('style');
  style.textContent = `
    .multi-text-result{grid-column:1/-1;width:100%;box-sizing:border-box;padding:14px 16px;border:1px solid var(--border);border-radius:14px;background:var(--panel);white-space:pre-wrap;font-size:14px;line-height:1.55}
    .multi-text-result:empty{display:none}
    .routing-info-card{min-height:0!important}
    .routing-info-card .routing-line{font-size:12px;line-height:1.5}
  `;
  document.head.appendChild(style);

  function textResult(message) {
    const el = document.createElement('div');
    el.className = 'multi-text-result';
    el.textContent = String(message || '').trim();
    return el;
  }

  function routingInfo(card, message) {
    const wrap = document.createElement('div');
    wrap.className = 'card-wrap';
    const el = document.createElement('div');
    el.className = 'result-card routing-info-card';
    wrap.appendChild(el);
    if (message) {
      const top = document.createElement('div');
      top.className = 'card-topline';
      top.textContent = message;
      el.appendChild(top);
    }
    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = '⚡ Routing';
    el.appendChild(title);
    const line = document.createElement('div');
    line.className = 'routing-line';
    const calls = Number(card.provider_calls || 0);
    const provider = card.provider || 'none';
    const route = card.route || (calls ? 'hybrid' : 'local');
    line.textContent = calls > 0
      ? `${route} · ${calls} ${provider} provider call${calls === 1 ? '' : 's'}`
      : `${route} · no ${provider === 'none' ? 'model' : provider} provider call required`;
    el.appendChild(line);
    return wrap;
  }

  window.renderCard = function(card, message) {
    if (card && card.type === 'routing_info') return routingInfo(card, message);

    if (card && card.type === 'multi') {
      const rendered = previousRenderCard(card, message);
      const grid = rendered instanceof HTMLElement ? rendered : null;
      if (!grid) return rendered;

      // cards.js deliberately renders card-backed items. Add all meaningful
      // text-only entries afterwards so hybrid LLM output can never disappear.
      for (const item of card.items || []) {
        if (!item || item.card) continue;
        const text = String(item.message || '').trim();
        if (text) grid.appendChild(textResult(text));
      }
      return grid;
    }

    return previousRenderCard(card, message);
  };
})();
