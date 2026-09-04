import { Monitor, SidebarSimple } from '@phosphor-icons/react'

export function WorkspaceHeader() {
  return (
    <header className="workspace-topbar">
      <div className="top-agent">
        <button className="top-agent-orb" type="button" aria-label="Open agent profile">A</button>
        <div className="top-agent-copy">
          <strong>New Agentie</strong>
          <small>Ready</small>
        </div>
      </div>

      <div className="workspace-actions">
        <button className="sidebar-toggle icon-button" type="button" title="Toggle agent sidebar" aria-label="Toggle agent sidebar">
          <SidebarSimple aria-hidden="true" weight="regular" />
        </button>
        <button className="topbar-button icon-button" type="button" title="Open computer" aria-label="Open computer">
          <Monitor aria-hidden="true" weight="regular" />
        </button>
      </div>
    </header>
  )
}
