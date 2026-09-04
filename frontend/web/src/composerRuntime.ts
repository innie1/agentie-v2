export function initializeComposerRuntime() {
  const composer = document.querySelector<HTMLElement>('.composer')
  const input = document.getElementById('messageInput') as HTMLTextAreaElement | null
  const button = document.getElementById('sendButton') as HTMLButtonElement | null
  if (!composer || !input || !button) return () => undefined
  const sync = () => {
    const hasText = Boolean(input.value.trim())
    composer.classList.toggle('has-text', hasText)
    button.title = hasText ? 'Send message' : 'Voice input'
    button.setAttribute('aria-label', button.title)
    input.style.height = 'auto'
    input.style.height = `${Math.min(input.scrollHeight, 142)}px`
  }
  type Recognition = { lang: string; interimResults: boolean; continuous: boolean; start(): void; stop(): void; onresult?: (event: { results: ArrayLike<{ 0: { transcript: string } }> }) => void; onend?: () => void; onerror?: () => void }
  const speechWindow = window as typeof window & { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition }
  const RecognitionCtor = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition
  let recognition: Recognition | null = null
  let listening = false
  const stopListening = () => recognition?.stop()
  const startListening = () => {
    if (!RecognitionCtor) { input.focus(); return }
    if (!recognition) {
      recognition = new RecognitionCtor(); recognition.lang = navigator.language || 'en-US'; recognition.interimResults = false; recognition.continuous = false
      recognition.onresult = event => { const transcript = event.results[0]?.[0]?.transcript?.trim(); if (transcript) input.value = `${input.value}${input.value ? ' ' : ''}${transcript}`; input.dispatchEvent(new Event('input', { bubbles: true })) }
      recognition.onend = () => { listening = false; composer.classList.remove('is-listening') }
      recognition.onerror = recognition.onend
    }
    listening = true; composer.classList.add('is-listening'); recognition.start()
  }
  input.addEventListener('input', sync)
  button.addEventListener('click', event => { if (input.value.trim()) return; event.preventDefault(); event.stopImmediatePropagation(); if (listening) stopListening(); else startListening() }, true)
  sync()
  return () => { input.removeEventListener('input', sync); if (listening) stopListening() }
}
