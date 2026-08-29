import { useEffect, useState } from 'react'

const runtimeScripts = [
  '/legacy-core.js?v=300', '/cards.js?v=201', '/events.js?v=201', '/upload.js?v=201',
  '/plugins.js?v=208', '/plugin-setup.js?v=207', '/telegram-plugin.js?v=201',
  '/plugin-access.js?v=203', '/browser-screen.js?v=201', '/ui-upgrade.js?v=203', '/platform.js?v=211',
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
    ;(async () => {
      try {
        for (const src of runtimeScripts) await loadScript(src)
      } catch (error) {
        if (active) setRuntimeError(error instanceof Error ? error.message : 'Agentie could not start.')
      }
    })()
    return () => { active = false }
  }, [])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">Agentie</div>
        <div className="subtle">Local-first agent workspace</div>
        <div className="agent-label">Your agents</div>
        <div id="persistentAgentList" className="agent-list" />
        <label className="agent-label base-agent-label" htmlFor="agentType">Base agent</label>
        <select id="agentType" defaultValue="general" aria-label="Choose base agent">
          <option value="general">General</option>
          <option value="research">Research</option>
          <option value="coding">Coding</option>
          <option value="manager">Manager</option>
          <option value="github">GitHub</option>
        </select>
      </aside>
      <main className="chat-shell">
        <div id="messages" className="messages" aria-live="polite">
          <div className="assistant-row"><div className="bubble assistant">What would you like Agentie to do?</div></div>
          {runtimeError && <div className="assistant-row"><div className="bubble assistant error-message">{runtimeError}</div></div>}
        </div>
        <div className="composer-wrap">
          <div className="composer">
            <textarea id="messageInput" rows={1} placeholder="Message Agentie..." aria-label="Message Agentie" />
            <button id="sendButton" type="button">Send</button>
          </div>
        </div>
      </main>
    </div>
  )
}
