import { ArrowClockwise, CaretLeft, Monitor, X } from '@phosphor-icons/react'

export function ComputerPanel() {
  return (
    <aside className="right-panel" aria-label="Agent computer">
      <div className="right-head">
        <div>
          <strong className="computer-agent-name">New Agentie&apos;s Computer</strong>
          <small>Company workspace</small>
        </div>
        <div className="right-head-actions">
          <button className="computer-reconnect icon-button" type="button" title="Start or reconnect computer" aria-label="Start or reconnect computer">
            <ArrowClockwise aria-hidden="true" />
          </button>
          <button className="right-close icon-button" type="button" title="Close computer" aria-label="Close computer">
            <X aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="computer-panel-body">
        <div className="computer-panel-stage">
          <div className="computer-panel-empty">
            <Monitor className="computer-placeholder-icon" aria-hidden="true" />
            <strong>Computer is ready when you need it</strong>
            <span>Start the workspace to browse, use apps, and work alongside this agent.</span>
            <button className="computer-start" type="button">Start computer</button>
          </div>
        </div>
        <div className="computer-panel-title">New Agentie&apos;s Computer</div>
        <section className="routine-section" aria-label="Agent routines">
          <div className="routine-list" />
          <div className="routine-empty"><span>Routines are recurring tasks this agent runs on a schedule.</span><button className="routine-create" type="button">Create Routine</button></div>
        </section>
      </div>
      <section className="agent-settings-panel" aria-label="Agent profile settings">
        <header className="agent-settings-head">
          <button className="agent-settings-back icon-button" type="button" aria-label="Close agent settings"><CaretLeft aria-hidden="true" /></button>
          <strong>Settings</strong>
          <button className="agent-settings-close icon-button" type="button" aria-label="Close agent settings"><X aria-hidden="true" /></button>
        </header>
        <div className="agent-settings-scroll">
          <div className="agent-settings-avatar" aria-hidden="true" />
          <label>Name<input data-profile-field="name" /></label>
          <label>Title<input data-profile-field="role" placeholder="Describe what this agent does" /></label>
          <label>Description<textarea data-profile-field="personality" placeholder="What this agent is for" /></label>
          <label>Goal<textarea data-profile-field="goal" placeholder="What this agent should achieve" /></label>
          <label>Instructions<textarea className="agent-settings-instructions" data-profile-field="instructions" placeholder="Durable working instructions for this agent" /></label>
          <label className="agent-settings-notifications"><span><strong>Notifications</strong><small>Get notified when this agent finishes or needs input</small></span><input data-profile-field="notifications" type="checkbox" /></label>
          <div className="agent-settings-status" role="status" />
          <button className="agent-settings-save" type="button">Save settings</button>
        </div>
      </section>
    </aside>
  )
}
