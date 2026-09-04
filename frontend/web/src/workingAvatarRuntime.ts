function copyActiveAvatar(target: HTMLElement) {
  const source = document.querySelector<HTMLElement>('.top-agent-orb')
    ?? document.querySelector<HTMLElement>('#persistentAgentList .agent-row.active .agent-orb')
  if (!source) return

  const computed = getComputedStyle(source)
  target.style.backgroundImage = computed.backgroundImage
  target.style.backgroundColor = 'transparent'
  target.style.backgroundSize = computed.backgroundSize
  target.style.backgroundPosition = computed.backgroundPosition
  target.style.backgroundRepeat = computed.backgroundRepeat
  const avatarVariable = source.style.getPropertyValue('--agent-avatar')
    || computed.getPropertyValue('--agent-avatar')
  if (avatarVariable) target.style.setProperty('--agent-avatar', avatarVariable)
}

function shouldDecorate(row: HTMLElement) {
  if (row.dataset.replyAvatar || row.classList.contains('welcome-row')) return false
  return Boolean(row.querySelector('.working, .bubble.assistant, .card-wrap, .result-card'))
}

function decorate(row: HTMLElement) {
  if (!shouldDecorate(row)) return
  row.dataset.replyAvatar = 'true'
  row.classList.add('agent-reply-row')

  const avatar = document.createElement('div')
  avatar.className = 'reply-agent-avatar'
  avatar.setAttribute('aria-hidden', 'true')
  copyActiveAvatar(avatar)
  row.insertBefore(avatar, row.firstChild)

  if (row.querySelector('.working')) {
    row.classList.add('agent-is-working')
    const working = row.querySelector<HTMLElement>('.working')
    if (working) {
      const label = working.querySelector<HTMLElement>(':scope > span:first-child')
      if (label) label.classList.add('working-label')
    }
  }
}

export function initializeWorkingAvatarRuntime() {
  const messages = document.getElementById('messages')
  if (!messages) return () => undefined

  const decorateAll = () => {
    messages.querySelectorAll<HTMLElement>('.assistant-row').forEach(decorate)
  }
  decorateAll()

  const observer = new MutationObserver(decorateAll)
  observer.observe(messages, { childList: true, subtree: true })

  const refreshAvatars = () => {
    messages.querySelectorAll<HTMLElement>('.reply-agent-avatar').forEach(copyActiveAvatar)
  }
  document.addEventListener('click', refreshAvatars)

  return () => {
    observer.disconnect()
    document.removeEventListener('click', refreshAvatars)
  }
}
