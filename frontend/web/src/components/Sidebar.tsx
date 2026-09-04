import { CaretLeft, MagnifyingGlass, Plus } from '@phosphor-icons/react'
import { openQuestion } from '../profilePromptRuntime'

export function Sidebar() {
  return (
    <aside className="sidebar" aria-label="Agent navigation">
      <div className="sidebar-head">
        <div className="brand">Agentie</div>
        <button className="sidebar-rail-toggle icon-button" type="button" title="Collapse sidebar" aria-label="Collapse sidebar">
          <CaretLeft aria-hidden="true" weight="bold" />
        </button>
        <button className="agent-create icon-button" type="button" title="Create agent" aria-label="Create agent" onClick={openQuestion}>
          <Plus aria-hidden="true" weight="regular" />
        </button>
      </div>

      <label className="agent-search-wrap">
        <MagnifyingGlass aria-hidden="true" />
        <input className="agent-search" type="search" placeholder="Search agents" aria-label="Search agents" />
      </label>

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
  )
}
