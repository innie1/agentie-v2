# Agentie v2

Agentie is a local-first multi-agent workspace for creating persistent AI agents that can remember, delegate, collaborate, use tools, run scheduled work, browse the web, and operate a real Linux desktop.

The project is Python-first with a FastAPI backend and a lightweight web UI. Agentie prefers deterministic/local execution for work that does not require a large model and falls back to configured AI providers for reasoning-heavy tasks.

## Current capabilities

### Persistent agents
- Create multiple named agents with roles and purposes.
- Persistent per-agent identity, sessions, instructions and memory scope.
- Rename agents and change roles dynamically.
- Manager/worker hierarchy and delegation permissions.
- Permanent agent deletion with private memory/chat/semantic-data purge.
- Agent-to-agent handoffs and simultaneous team jobs.
- Missing-agent suggestions that can create the requested specialist or route work to a similar existing agent.

### Agent instructions and local NPC brains
- Generated system instructions from agent identity, role, purpose and permissions.
- User-editable instructions with higher priority than learned defaults.
- Conversation-based preference learning without copying full chats into prompts.
- Learning audit with compact structured changes.
- Role-aware local NPC responses for common conversation and role-specific workflows.
- Local-first routing avoids provider calls for supported deterministic tasks.

### Jobs, approvals and orchestration
- Multi-step background jobs with progress and provider-call budgets.
- Pause, resume and retry controls.
- Team jobs and handoffs between persistent agents.
- Approval gates for consequential actions such as permanent deletion.
- Execution traces with routing, provider/model, latency, token usage and status information.

### Memory
- Persistent user and agent memory.
- Explicit `Remember that...` commands.
- Semantic memory search/shards.
- Per-agent isolation so private agent conversations are not silently shared.
- Learned communication/task preferences become part of an agent's evolving instruction profile.

### Reminders and routines
- Timers and one-time reminders.
- Modify active timers using remaining time.
- Recurring routines including weekday schedules.
- Background routine worker for scheduled prompts/tasks.

### Native/local tools
Agentie includes local tools and routing for capabilities such as:
- Local date/time
- Calculator and unit conversion
- Timers/reminders
- Notes and scratchpad
- Memory
- Agent/role management
- Routines
- File/archive operations
- Research and browser workflows
- Code execution and workspace operations

### Skills, plugins and MCP
- Skill registry and role/skill routing infrastructure.
- Plugin/MCP architecture for external capabilities.
- Capability preflight and approval infrastructure.
- Direction includes integrations such as GitHub, Gmail, Google Calendar, Slack, Notion and browser/web tools.

Some integrations still require additional connection, permission and end-user UI work before they should be considered complete product integrations.

### Browser and research
- Browser automation infrastructure.
- Website screenshots and interaction workflows.
- Website monitoring infrastructure.
- Deep research and citation verification components.
- Browser/Computer fallback is an active development area.

### Agentie's Computer
Agentie can expose a real Ubuntu/XFCE graphical desktop running under WSL and KasmVNC.

Current Computer stack includes:
- Ubuntu/WSL desktop
- XFCE graphical environment
- KasmVNC access
- Embedded Computer card
- Fullscreen Computer view
- Mouse and keyboard interaction
- Resize/reconnection handling
- Window controls
- Browser, terminal and files inside the desktop

The Computer is intended to become an execution environment agents can use when normal tools/plugins are insufficient. Autonomous visual operation and automatic fallback routing are still being hardened.

### Web UI
The current UI includes:
- Persistent agent sidebar and agent switching
- Agent chat
- Agent search/create controls
- Agent information/instructions editing
- Native cards for jobs and instructions
- Approval UI
- Attachments
- Computer window/card
- Collapsible workspace panels
- Routines panel

## Architecture

```text
agentie-v2/
├── agentie/
│   ├── agents/              # assistant definitions
│   ├── core/                # agents, memory, jobs, routing, browser, Computer, skills
│   ├── models/              # AI provider configuration
│   └── tools/               # local/native tools
├── frontend/                # Agentie web UI
├── tests/                   # regression suite
├── workspace/               # local agent workspace/runtime data
├── main.py                  # FastAPI application
├── pyproject.toml
└── README.md
```

Important core modules include `agent_registry.py`, `agent_prompt.py`, `npc_brain.py`, `job_engine.py`, `team_orchestrator.py`, `memory_store.py`, `advanced_local_router.py`, `capability_router.py`, `browser_automation.py`, and `computer_session.py`.

## Local-first execution philosophy

Agentie should not call a paid/remote model for work that can be handled safely and deterministically on-device.

The intended routing order is broadly:

1. Parse obvious native/local commands.
2. Use agent NPC/local intelligence for supported conversation and role behavior.
3. Use skills/plugins/tools when a capability is available.
4. Use a configured large model when genuine reasoning/generation is needed.
5. Use Browser/Computer execution when direct integrations are unavailable or insufficient.

Provider failure should therefore affect only work that genuinely requires that provider, not timers, local conversation, job controls, memory commands, or other supported local operations.

## Run locally

Python 3.10+ is required. Python 3.11 is currently used during development.

```powershell
cd C:\Users\user\agentie-v2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
python main.py
```

Create a `.env` from `.env.example` and configure the provider settings required by your environment. Never commit real API keys or secrets.

## Tests

Agentie uses regression tests heavily because new capabilities must not break existing agents, memory, Computer, jobs or routing.

Run the complete regression suite after every meaningful change:

```powershell
python -m unittest discover -s tests -p "test_*regression.py" -v
```

For a new feature, run its targeted regression file first, then run the full suite.

## Development rules

When extending Agentie:

1. Inspect existing functionality before adding new code.
2. Do not duplicate an existing subsystem.
3. Prefer the smallest safe patch over broad rewrites.
4. Preserve backend/API contracts during UI-only changes.
5. Keep local operations local where possible.
6. Require approvals for consequential/irreversible operations.
7. Preserve per-agent memory isolation.
8. Add regression tests for new behavior.
9. Do not merge a feature while existing regressions are failing.
10. Keep this README updated as major capabilities are added.

## Current development roadmap

The next major capability work is intentionally focused on the underlying agent intelligence before final UI polish.

### 1. Expand local NPC intelligence — next
Build a broader lightweight local reasoning layer so agents can understand more everyday conversation, contextual follow-ups, role-specific requests and deterministic workflows without unnecessarily calling a paid model. This must remain compatible with evolving agent instructions and learned user preferences.

### 2. Computer autonomy and automatic fallback
Allow Agentie to choose Browser/Computer execution when an API/plugin cannot complete a task, then observe, interact and verify the result reliably.

### 3. Skills and plugin permissions
Build a complete user-facing skills/plugins system with per-agent capability permissions, connection state and safe approvals.

### 4. Background/routine reliability
Harden scheduled work, restart recovery, missed-run behavior, job continuation and failure recovery.

### 5. Voice
Turn the microphone UI into a complete speech-input workflow and later support richer voice interaction.

### 6. Integration hardening
Finish end-user connection and reliability flows for services such as GitHub, Gmail, Calendar, Slack and Notion.

### 7. Authentication/accounts
Add production user/account isolation if Agentie moves from a local personal workspace into a multi-user product.

### 8. Final UI/UX polish
Once the underlying capabilities are stable, finish the cohesive desktop/web experience around those stable contracts.

## Status

Agentie v2 is under active development. It already has a substantial working agent runtime; the current focus is making that runtime more autonomous, local-first, reliable and capable before treating the UI as final.