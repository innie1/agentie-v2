const semanticIcons: Array<[RegExp, string]> = [
  [/telegram/i, 'si si-telegram'], [/whatsapp/i, 'si si-whatsapp'], [/github/i, 'si si-github'], [/^git$/i, 'si si-git'], [/google workspace|google/i, 'si si-google'],
  [/browser|playwright|fetch/i, 'ph ph-browser'], [/code|execution|sequential/i, 'ph ph-code'], [/email|agentmail/i, 'ph ph-envelope'],
  [/file|document|filesystem|drive/i, 'ph ph-folder-open'], [/job|delegation|agent/i, 'ph ph-users-three'], [/knowledge|memory|reasoning|research/i, 'ph ph-brain'],
  [/time|timer|routine|local utilities/i, 'ph ph-clock'], [/sport|finance|analytics/i, 'ph ph-chart-line'], [/visual|motion|canva|design/i, 'ph ph-image'],
  [/last30days/i, 'ph ph-calendar-dots'], [/everything|mcp|server/i, 'ph ph-plugs-connected'],
]
const officialBrandImages: Array<[RegExp, string]> = [
  [/^playwright$/i, '/assets/plugin-icons/playwright.svg'],
  [/^agentmail$/i, '/assets/plugin-icons/agentmail.ico'],
]
function setIcon(host: Element | null, className: string, label?: string) {
  if (!host || host.getAttribute('data-icon-class') === className) return
  host.replaceChildren(); const icon = document.createElement('i'); icon.className = className; icon.setAttribute('aria-hidden', 'true'); host.appendChild(icon); host.setAttribute('data-icon-class', className)
  if (label) host.setAttribute('title', label)
}
function setOfficialIcon(host: Element | null, source: string, fallback: string, label: string) {
  if (!host || host.getAttribute('data-icon-source') === source) return
  host.replaceChildren(); const image = document.createElement('img'); image.src = source; image.alt = ''; image.loading = 'lazy'; image.referrerPolicy = 'no-referrer'
  const icon = document.createElement('i'); icon.className = fallback; icon.setAttribute('aria-hidden', 'true'); icon.hidden = true
  image.onload = () => { icon.hidden = true }; image.onerror = () => { image.remove(); icon.hidden = false }
  host.append(image, icon); host.setAttribute('data-icon-source', source); host.setAttribute('title', label)
}
function refreshIcons() {
  setIcon(document.querySelector('.plugins-launch .plug-dot'), 'ph ph-puzzle-piece', 'Plugins')
  setIcon(document.querySelector('.plugins-mobile-launch'), 'ph ph-puzzle-piece', 'Plugins')
  setIcon(document.querySelector('.agentie-connected-profile-icon'), 'ph ph-user-circle', 'Profile')
  document.querySelectorAll('.mcp-row').forEach(row => {
    const name = row.querySelector('.mcp-name')?.textContent?.trim() || ''
    const match = semanticIcons.find(([pattern]) => pattern.test(name))
    const brand = officialBrandImages.find(([pattern]) => pattern.test(name))
    if (brand) setOfficialIcon(row.querySelector('.mcp-icon'), brand[1], match?.[1] || 'ph ph-puzzle-piece', name)
    else setIcon(row.querySelector('.mcp-icon'), match?.[1] || 'ph ph-puzzle-piece', name)
  })
}
export function initializeIconRuntime() {
  const observer = new MutationObserver(refreshIcons); observer.observe(document.body, { childList: true, subtree: true })
  const timer = window.setInterval(refreshIcons, 500); refreshIcons()
  return () => { observer.disconnect(); window.clearInterval(timer) }
}
