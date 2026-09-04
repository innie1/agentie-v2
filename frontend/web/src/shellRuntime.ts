type AgentRecord = { id?: string; name?: string; role?: string; job?: string; base?: string }

declare global {
  interface Window {
    __agentieAgents?: AgentRecord[]
    __agentieActiveGroupChat?: { name?: string }
  }
}

const FALLBACK_AGENT_NAME = 'New Agentie'

function activeAgent(): AgentRecord | null {
  const row = document.querySelector<HTMLElement>('#persistentAgentList .agent-row.active, #persistentAgentList .agent-row')
  if (!row) return null
  const id = row.dataset.agentId
  const name = row.querySelector('.agent-copy strong')?.textContent?.trim()
  return (window.__agentieAgents || []).find(agent => (id && agent.id === id) || agent.name === name) || null
}

function setShellState(shell: HTMLElement, key: 'sidebar' | 'computer', open: boolean) {
  shell.dataset[key] = open ? 'open' : 'closed'
  shell.classList.toggle(key === 'sidebar' ? 'sidebar-collapsed' : 'right-open', !open === (key === 'sidebar'))
  if (key === 'sidebar') {
    const label = open ? 'Collapse sidebar' : 'Expand sidebar'
    const toggle = document.querySelector<HTMLElement>('.sidebar-rail-toggle')
    toggle?.setAttribute('aria-label', label)
    toggle?.setAttribute('title', label)
  }
  if (key === 'sidebar') localStorage.setItem('agentie.sidebar.open', open ? '1' : '0')
}

function dispatchChat(message: string) {
  const input = document.getElementById('messageInput') as HTMLTextAreaElement | null
  const send = document.getElementById('sendButton') as HTMLButtonElement | null
  if (!input || !send) return
  input.value = message
  input.dispatchEvent(new Event('input', { bubbles: true }))
  send.click()
}

export function initializeShellRuntime() {
  const shell = document.querySelector<HTMLElement>('[data-shell-v2]')
  const search = document.querySelector<HTMLInputElement>('.agent-search')
  const sidebarToggle = document.querySelector<HTMLButtonElement>('.sidebar-toggle')
  const sidebarRailToggle = document.querySelector<HTMLButtonElement>('.sidebar-rail-toggle')
  const computerOpen = document.querySelector<HTMLButtonElement>('.topbar-button')
  const computerClose = document.querySelector<HTMLButtonElement>('.right-close')
  const computerReconnect = document.querySelector<HTMLButtonElement>('.computer-reconnect')
  const computerStart = document.querySelector<HTMLButtonElement>('.computer-start')
  const computerStage = document.querySelector<HTMLElement>('.computer-panel-stage')
  if (!shell) return () => undefined

  const mobile = window.matchMedia('(max-width:720px)').matches
  setShellState(shell, 'sidebar', mobile ? false : localStorage.getItem('agentie.sidebar.open') !== '0')
  setShellState(shell, 'computer', false)

  sidebarToggle?.addEventListener('click', () => setShellState(shell, 'sidebar', shell.dataset.sidebar !== 'open'))
  sidebarRailToggle?.addEventListener('click', () => setShellState(shell, 'sidebar', shell.dataset.sidebar !== 'open'))
  computerOpen?.addEventListener('click', () => setShellState(shell, 'computer', true))
  computerClose?.addEventListener('click', () => setShellState(shell, 'computer', false))
  const startComputer = () => { setShellState(shell, 'computer', true); dispatchChat('Show desktop') }
  computerReconnect?.addEventListener('click', startComputer)
  computerStart?.addEventListener('click', startComputer)

  search?.addEventListener('input', () => {
    const query = search.value.trim().toLowerCase()
    document.querySelectorAll<HTMLElement>('#persistentAgentList .agent-row').forEach(row => {
      row.hidden = Boolean(query && !row.textContent?.toLowerCase().includes(query))
    })
  })

  const dockComputer = () => {
    const computer = document.querySelector<HTMLElement>('.agentie-real-computer')
    if (computer && computerStage && !computerStage.contains(computer)) computerStage.replaceChildren(computer)
  }
  const observer = new MutationObserver(dockComputer)
  observer.observe(document.body, { childList: true, subtree: true })
  dockComputer()

  const syncAgentIdentity = () => {
    const agent = activeAgent()
    const name = window.__agentieActiveGroupChat?.name || agent?.name || FALLBACK_AGENT_NAME
    const role = window.__agentieActiveGroupChat ? 'Group chat' : agent?.role || 'Ready'
    const title = document.querySelector<HTMLElement>('.top-agent-copy strong')
    const subtitle = document.querySelector<HTMLElement>('.top-agent-copy small')
    const panelName = document.querySelector<HTMLElement>('.computer-agent-name')
    const panelCaption = document.querySelector<HTMLElement>('.computer-panel-title')
    if (title) title.textContent = name
    if (subtitle) subtitle.textContent = role
    const welcome = document.querySelector<HTMLElement>('.welcome-line')
    if (welcome) welcome.textContent = `Chatting with ${name}${agent?.job || agent?.role ? ` · ${agent?.job || agent?.role}` : ''}`
    if (panelName) panelName.textContent = `${name}'s Computer`
    if (panelCaption) panelCaption.textContent = `${name}'s Computer`
  }
  const syncTimer = window.setInterval(syncAgentIdentity, 300)
  syncAgentIdentity()

  return () => { observer.disconnect(); window.clearInterval(syncTimer) }
}
