export function openQuestion() {
  document.querySelector('.agent-profile-question')?.remove()
  const messages = document.getElementById('messages'); if (!messages) return
  const card = document.createElement('section'); card.className = 'agent-profile-question'
  card.innerHTML = `<button class="agent-profile-question-close" type="button" aria-label="Cancel">×</button><h3>What should I help with first?</h3><div class="agent-profile-question-grid"></div><input class="agent-profile-question-own" placeholder="Type your own answer" aria-label="Type your own answer">`
  const choices = [['A','Work / business'],['B','Personal life'],['C','A mix of both'],['D',"I'll tell you"]]
  const grid = card.querySelector('.agent-profile-question-grid')!
  const finish = (answer: string) => { localStorage.setItem('agentie.newAgent.focus', answer); card.remove() }
  choices.forEach(([key,label]) => { const button = document.createElement('button'); button.type = 'button'; button.innerHTML = `<span>${key}</span><strong>${label}</strong>`; button.onclick = () => finish(label); grid.appendChild(button) })
  const own = card.querySelector<HTMLInputElement>('.agent-profile-question-own')!; own.addEventListener('keydown', event => { if (event.key === 'Enter' && own.value.trim()) finish(own.value.trim()) })
  card.querySelector<HTMLButtonElement>('.agent-profile-question-close')!.onclick = () => card.remove()
  const welcome = messages.querySelector('.welcome-row')
  if (welcome) welcome.after(card); else messages.prepend(card)
}
export function initializeProfilePromptRuntime() {
  const onClick = (event: Event) => {
    const target = event.target as Element | null
    if (target?.closest('.top-agent-orb')) {
      event.preventDefault(); event.stopImmediatePropagation(); window.dispatchEvent(new CustomEvent('agentie:open-profile'))
      return
    }
  }
  document.addEventListener('click', onClick, true)
  return () => document.removeEventListener('click', onClick, true)
}
