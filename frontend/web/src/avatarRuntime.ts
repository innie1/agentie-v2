type AgentRecord = { id?: string; name?: string; avatar_kind?: string; avatar_url?: string }
declare global {
  interface Window {
    __agentieAgents?: AgentRecord[]
    __agentieAvatarFor?: (agent: AgentRecord | string | null | undefined) => string
    __agentiePaintAvatar?: (element: HTMLElement, agent: AgentRecord | string | null | undefined) => void
  }
}
const variants = [
  { id: 'circle-blue', label: 'Blue orb', src: '/assets/agent-avatars/orb-circle-blue.png' },
  { id: 'hex-violet', label: 'Violet hex', src: '/assets/agent-avatars/orb-hex-violet.png' },
  { id: 'pebble-teal', label: 'Teal pebble', src: '/assets/agent-avatars/orb-pebble-teal.png' },
  { id: 'triangle-coral', label: 'Coral triangle', src: '/assets/agent-avatars/orb-triangle-coral.png' },
] as const
const storageKey = 'agentie.avatar.assignments.v1'
let pendingChoice = ''
let knownAgentIds = new Set<string>()
function readAssignments(): Record<string, string> { try { return JSON.parse(localStorage.getItem(storageKey) || '{}') || {} } catch { return {} } }
function writeAssignments(value: Record<string, string>) { localStorage.setItem(storageKey, JSON.stringify(value)) }
function keyFor(agent: AgentRecord) { return String(agent.id || agent.name || 'new-agentie') }
function variantFor(agent: AgentRecord) {
  const map = readAssignments(), key = keyFor(agent); let id = map[key]
  if (!variants.some(item => item.id === id)) { id = variants[Math.floor(Math.random() * variants.length)].id; map[key] = id; writeAssignments(map) }
  return variants.find(item => item.id === id) || variants[0]
}
function resolveAgent(value: AgentRecord | string | null | undefined): AgentRecord {
  if (value && typeof value === 'object') return value
  const token = String(value || '')
  return (window.__agentieAgents || []).find(agent => agent.id === token || agent.name === token) || { id: token, name: token || 'New Agentie' }
}
function avatarFor(value: AgentRecord | string | null | undefined) {
  const agent = resolveAgent(value)
  return agent.avatar_kind === 'uploaded' && agent.avatar_url ? agent.avatar_url : variantFor(agent).src
}
function paintAvatar(element: HTMLElement, value: AgentRecord | string | null | undefined) {
  const src = avatarFor(value)
  element.style.setProperty('--agent-avatar', `url("${src}")`)
  element.style.setProperty('background-image', `url("${src}")`, 'important')
  element.style.setProperty('background-color', 'transparent', 'important')
  element.style.setProperty('background-size', 'cover', 'important')
  element.style.setProperty('background-position', 'center', 'important')
  element.style.setProperty('background-repeat', 'no-repeat', 'important')
  element.style.setProperty('color', 'transparent', 'important')
  element.textContent = ''
}
function activeAgent(): AgentRecord {
  const row = document.querySelector<HTMLElement>('#persistentAgentList .agent-row.active, #persistentAgentList .agent-row'), id = row?.dataset.agentId, name = row?.querySelector('.agent-copy strong')?.firstChild?.textContent?.trim()
  return ((window as typeof window & { __agentieAgents?: AgentRecord[] }).__agentieAgents || []).find(agent => agent.id === id || agent.name === name) || { name: 'New Agentie' }
}
function paint() {
  const agents = (window as typeof window & { __agentieAgents?: AgentRecord[] }).__agentieAgents || []
  document.querySelectorAll<HTMLElement>('#persistentAgentList .agent-row').forEach(row => {
    const name = row.querySelector('.agent-copy strong')?.firstChild?.textContent?.trim(), agent: AgentRecord = agents.find(item => item.id === row.dataset.agentId || item.name === name) || { id: row.dataset.agentId, name }, orb = row.querySelector<HTMLElement>('.agent-orb')
    if (orb) paintAvatar(orb, agent)
  })
  const topOrb = document.querySelector<HTMLElement>('.top-agent-orb'); if (topOrb) paintAvatar(topOrb, activeAgent())
  document.querySelectorAll<HTMLElement>('[data-agent-id].agentie-connected-group-dot,[data-agent-id].agentie-connected-sidebar-dot,[data-agent-id].agentie-connected-group-message-orb,[data-agent-id].agentie-at-orb,[data-agent-id].team-worker-orb,[data-agent-id].collab-orb,.chat-agent-orb[data-agent-id],.handoff-consent-orb[data-agent-id]').forEach(element => paintAvatar(element, element.dataset.agentId || element.dataset.agentName))
}
function installPicker(panel: HTMLElement) {
  if (panel.querySelector('.avatar-picker')) return
  const actions = panel.querySelector('.platform-actions'); if (!actions) return
  const picker = document.createElement('section'); picker.className = 'platform-section avatar-picker'
  picker.innerHTML = `<div class="platform-section-title">Choose an avatar</div><div class="avatar-picker-options"><button type="button" class="avatar-choice active" data-avatar="auto"><span>Auto</span></button>${variants.map(item => `<button type="button" class="avatar-choice" data-avatar="${item.id}" title="${item.label}"><img src="${item.src}" alt="${item.label}"></button>`).join('')}</div><div class="platform-help">Pick a character, or leave Auto selected for a random one.</div>`
  actions.before(picker)
  picker.querySelectorAll<HTMLButtonElement>('.avatar-choice').forEach(button => button.onclick = () => { picker.querySelectorAll('.avatar-choice').forEach(item => item.classList.remove('active')); button.classList.add('active') })
  actions.querySelector<HTMLButtonElement>('[data-create]')?.addEventListener('click', () => {
    const selected = picker.querySelector<HTMLElement>('.avatar-choice.active')?.dataset.avatar, name = panel.querySelector<HTMLInputElement>('[data-name]')?.value.trim(); if (!selected || selected === 'auto') return
    const assign = window.setInterval(() => { const agent = ((window as typeof window & { __agentieAgents?: AgentRecord[] }).__agentieAgents || []).find(item => item.name === name); if (!agent) return; const map = readAssignments(); map[keyFor(agent)] = selected; writeAssignments(map); paint(); window.clearInterval(assign) }, 250)
    window.setTimeout(() => window.clearInterval(assign), 8000)
  }, true)
}
function installOnboardingPicker(prompt: HTMLElement) {
  if (prompt.querySelector('.avatar-picker')) return
  const actions = prompt.querySelector('.agentie-create-actions'); if (!actions) return
  const picker = document.createElement('section'); picker.className = 'avatar-picker onboarding-avatar-picker'
  picker.innerHTML = `<div class="platform-section-title">Choose my avatar</div><div class="avatar-picker-options"><button type="button" class="avatar-choice active" data-avatar="auto"><span>Auto</span></button>${variants.map(item => `<button type="button" class="avatar-choice" data-avatar="${item.id}" title="${item.label}"><img src="${item.src}" alt="${item.label}"></button>`).join('')}</div><div class="platform-help">Auto gives the new agent a random character.</div>`
  actions.before(picker)
  knownAgentIds = new Set(((window as typeof window & { __agentieAgents?: AgentRecord[] }).__agentieAgents || []).map(item => keyFor(item)))
  picker.querySelectorAll<HTMLButtonElement>('.avatar-choice').forEach(button => button.onclick = () => { picker.querySelectorAll('.avatar-choice').forEach(item => item.classList.remove('active')); button.classList.add('active'); pendingChoice = button.dataset.avatar || '' })
}
export function initializeAvatarRuntime() {
  window.__agentieAvatarFor = avatarFor
  window.__agentiePaintAvatar = paintAvatar
  const refresh = () => { document.querySelectorAll<HTMLElement>('.platform-panel').forEach(installPicker); document.querySelectorAll<HTMLElement>('.agentie-create-prompt').forEach(installOnboardingPicker); paint() }
  const observer = new MutationObserver(refresh); observer.observe(document.body, { childList: true, subtree: true })
  const timer = window.setInterval(() => {
    refresh()
    if (pendingChoice && !document.querySelector('.agentie-create-onboarding')) {
      const created = ((window as typeof window & { __agentieAgents?: AgentRecord[] }).__agentieAgents || []).find(item => !knownAgentIds.has(keyFor(item)))
      if (created && pendingChoice !== 'auto') { const map = readAssignments(); map[keyFor(created)] = pendingChoice; writeAssignments(map) }
      if (created) pendingChoice = ''
    }
  }, 300); paint()
  return () => { observer.disconnect(); window.clearInterval(timer); delete window.__agentieAvatarFor; delete window.__agentiePaintAvatar }
}
