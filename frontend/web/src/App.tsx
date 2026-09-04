import { useEffect, useState } from 'react'
import { ArrowUp, Microphone, Plus } from '@phosphor-icons/react'
import { ComputerPanel } from './components/ComputerPanel'
import { Sidebar } from './components/Sidebar'
import { WorkspaceHeader } from './components/WorkspaceHeader'
import { initializeShellRuntime } from './shellRuntime'
import { initializeAvatarRuntime } from './avatarRuntime'
import { initializeComposerRuntime } from './composerRuntime'
import { initializeIconRuntime } from './iconRuntime'
import { initializeProfilePromptRuntime } from './profilePromptRuntime'
import { initializeWorkingAvatarRuntime } from './workingAvatarRuntime'
import { initializeProfilePanelRuntime } from './profilePanelRuntime'

const runtimeScripts = [
  '/legacy-core.js?v=300', '/cards.js?v=201', '/events.js?v=201', '/upload.js?v=201',
  '/plugins.js?v=208', '/plugin-setup.js?v=207', '/telegram-plugin.js?v=201',
  '/plugin-access.js?v=203', '/browser-screen.js?v=201', '/platform.js?v=211',
]

function loadScript(src: string) {
  return new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.async = false
    script.onload = () => resolve()
    script.onerror = () => reject(new Error(`Unable to load ${src}`))
    document.body.appendChild(script)
  })
}

export function App() {
  const [runtimeError, setRuntimeError] = useState('')

  useEffect(() => {
    let active = true
    let disposeShell: () => void = () => undefined
    let disposeAvatars: () => void = () => undefined
    let disposeComposer: () => void = () => undefined
    let disposeIcons: () => void = () => undefined
    let disposeProfilePrompt: () => void = () => undefined
    let disposeWorkingAvatar: () => void = () => undefined
    let disposeProfilePanel: () => void = () => undefined
    ;(async () => {
      try {
        for (const src of runtimeScripts) await loadScript(src)
        if (active) { disposeShell = initializeShellRuntime(); disposeAvatars = initializeAvatarRuntime(); disposeComposer = initializeComposerRuntime(); disposeIcons = initializeIconRuntime(); disposeProfilePrompt = initializeProfilePromptRuntime(); disposeWorkingAvatar = initializeWorkingAvatarRuntime(); disposeProfilePanel = initializeProfilePanelRuntime() }
      } catch (error) {
        if (active) setRuntimeError(error instanceof Error ? error.message : 'Agentie could not start.')
      }
    })()
    return () => { active = false; disposeShell(); disposeAvatars(); disposeComposer(); disposeIcons(); disposeProfilePrompt(); disposeWorkingAvatar(); disposeProfilePanel() }
  }, [])

  return (
    <div className="app-shell" data-shell-v2 data-sidebar="open" data-computer="closed">
      <Sidebar />
      <main className="chat-shell">
        <WorkspaceHeader />
        <div id="messages" className="messages" aria-live="polite">
          <div className="assistant-row welcome-row"><div className="bubble assistant welcome-line">Chatting with New Agentie</div></div>
          {runtimeError && <div className="assistant-row"><div className="bubble assistant error-message">{runtimeError}</div></div>}
        </div>
        <div className="composer-wrap">
          <div className="composer">
            <button className="attach-button" type="button" title="Attach files" aria-label="Attach files">
              <Plus aria-hidden="true" weight="regular" />
            </button>
            <textarea id="messageInput" rows={1} placeholder="Message Agentie..." aria-label="Message Agentie" />
            <button id="sendButton" type="button" title="Voice input" aria-label="Voice input">
              <Microphone className="composer-mic-icon" aria-hidden="true" weight="fill" />
              <ArrowUp className="composer-send-icon" aria-hidden="true" weight="bold" />
            </button>
          </div>
        </div>
      </main>
      <ComputerPanel />
    </div>
  )
}
