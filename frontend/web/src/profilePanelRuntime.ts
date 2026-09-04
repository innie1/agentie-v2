type Agent = { id?: string; name?: string; role?: string; personality?: string; purpose?: string; goal?: string }

async function command(message: string, session = 'profile-settings') {
  const response = await fetch('/agent/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message, agent_type: 'general', session_id: `ui:${session}` }) })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || data.message || 'Could not update this agent.')
  return data
}

async function currentAgent(): Promise<Agent | null> {
  const row = document.querySelector<HTMLElement>('#persistentAgentList .agent-row.active, #persistentAgentList .agent-row')
  const id = row?.dataset.agentId, name = row?.querySelector('.agent-copy strong')?.firstChild?.textContent?.trim()
  const data = await command('Show my agents', 'profile-directory')
  const agents = data.card?.type === 'agents' ? data.card.items || [] : []
  return agents.find((agent: Agent) => (id && agent.id === id) || agent.name === name) || (id || name ? { id, name } : null)
}

export function initializeProfilePanelRuntime() {
  const shell = document.querySelector<HTMLElement>('[data-shell-v2]'), panel = document.querySelector<HTMLElement>('.agent-settings-panel')
  if (!shell || !panel) return () => undefined
  let agent: Agent | null = null
  const field = (name: string) => panel.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[data-profile-field="${name}"]`)!
  const status = panel.querySelector<HTMLElement>('.agent-settings-status')!, save = panel.querySelector<HTMLButtonElement>('.agent-settings-save')!
  const close = () => { shell.dataset.rightMode = 'computer'; shell.dataset.computer = 'closed'; shell.classList.remove('right-open') }
  const paintAvatar = () => {
    const source = document.querySelector<HTMLElement>('.top-agent-orb'), avatar = panel.querySelector<HTMLElement>('.agent-settings-avatar')
    if (!source || !avatar) return
    avatar.style.backgroundImage = getComputedStyle(source).backgroundImage
    avatar.style.setProperty('--agent-avatar', source.style.getPropertyValue('--agent-avatar'))
  }
  const open = async () => {
    shell.dataset.rightMode = 'profile'; shell.dataset.computer = 'open'; shell.classList.add('right-open'); status.textContent = 'Loading profile…'; paintAvatar()
    try {
      agent = await currentAgent(); if (!agent) throw new Error('Select an agent first.')
      field('name').value = agent.name || ''; field('role').value = agent.role || ''; field('personality').value = agent.personality || agent.purpose || ''; field('goal').value = agent.goal || ''
      const instructions = await command(`Show ${agent.id || agent.name} instructions`, 'profile-instructions')
      field('instructions').value = instructions.card?.manual_instructions || ''
      ;(field('notifications') as HTMLInputElement).checked = localStorage.getItem(`agentie.notifications.${agent.id || agent.name}`) !== '0'; status.textContent = ''
    } catch (error) { status.textContent = error instanceof Error ? error.message : 'Could not load profile.' }
  }
  const onOpen = () => void open()
  window.addEventListener('agentie:open-profile', onOpen)
  panel.querySelectorAll('.agent-settings-back,.agent-settings-close').forEach(button => button.addEventListener('click', close))
  save.addEventListener('click', async () => {
    if (!agent) return; save.disabled = true; status.textContent = 'Saving…'
    try {
      const id = agent.id || agent.name, name = field('name').value.trim(), role = field('role').value.trim(), personality = field('personality').value.trim(), goal = field('goal').value.trim(), instructions = field('instructions').value.trim()
      if (name && name !== agent.name) await command(`Rename agent ${id} to ${name}`)
      if (role && role !== agent.role) await command(`Change agent ${id} role to ${role}`)
      if (personality !== (agent.personality || agent.purpose || '')) await command(personality ? `Set agent ${id} personality to ${personality}` : `Clear agent ${id} personality`)
      if (goal !== (agent.goal || '')) await command(goal ? `Set agent ${id} goal to ${goal}` : `Clear agent ${id} goal`)
      if (instructions) await command(`Set agent ${id} instructions to ${instructions}`, 'profile-instructions')
      localStorage.setItem(`agentie.notifications.${id}`, (field('notifications') as HTMLInputElement).checked ? '1' : '0'); status.textContent = 'Saved.'
    } catch (error) { status.textContent = error instanceof Error ? error.message : 'Could not save settings.' } finally { save.disabled = false }
  })
  return () => window.removeEventListener('agentie:open-profile', onOpen)
}
