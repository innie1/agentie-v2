# Agentie v2

Agentie is a local-first multi-agent workspace for creating persistent AI agents that can remember, delegate, collaborate, use tools, run scheduled work, browse the web, and operate a real Linux desktop.

The project is Python-first with a FastAPI backend and a lightweight web UI. Agentie prefers deterministic/local execution for work that does not require a large model and falls back to configured AI providers for reasoning-heavy tasks.

## Current capabilities

### Persistent agents
- Create multiple named agents with roles and purposes.
- Persistent per-agent identity, sessions, instructions and memory scope.
- Rename agents and change roles dynamically.
- Pin/unpin agents from the sidebar or by command; pinned agents persist at the top and new agents remain below the pinned group.
- Manager/worker hierarchy and delegation permissions.
- Permanent agent deletion with private memory/chat/semantic-data purge.
- Agent-to-agent handoffs and simultaneous team jobs.
- Missing-agent suggestions that can create the requested specialist or route work to a similar existing agent.

### Projects / Project Brain
- Persistent long-running projects for apps, novels, screenplays, businesses, life goals and general work.
- Project Brain stores goals, decisions, distilled shared context, milestones, artifacts, handoffs and compact specialist summaries.
- Worker agents receive role-scoped project briefs instead of another agent's full private chat.
- Completed specialist output remains attached to that worker by default and is not automatically promoted into shared Project Brain knowledge; downstream sharing must be explicit.
- Legacy worker-result knowledge is filtered from other specialists' new handoff prompts unless it was explicitly marked shared.
- A project delegated to several agents remains one shared Project Brain and appears in every assigned agent's chat workspace.
- Each assigned-agent project view includes that agent's delegated task, role-scoped context, work status and latest result without exposing another worker's private context.
- Assigned-project list rows stay compact: they show task/status plus a short, Markdown-clean result title/summary instead of squeezing a whole report or raw formatting tokens into the list.
- **Open** in a worker workspace expands a full specialist workspace with that agent's task, status, scoped project context, full persisted handoff result rendered as readable Markdown, and project artifacts when present.
- Specialist workspaces render project context from the original scoped handoff brief that worker received, so later work by another specialist is not retroactively injected into that worker's visible context.
- Specialist workspace selection resolves the actual selected agent name independently of sidebar role badges, so role labels cannot break the Open action.
- The full specialist workspace reads only `Show projects for <agent>` plus that agent's own handoff history; it never fetches the global project to render recipient work.
- The final project-manager renderer preserves `viewer_assignment`; a worker-scoped project cannot be replaced by the global project view when the user presses **Open**.
- Project handoff tasks and results are mirrored into the receiving specialist's normal `main` chat timeline, and the selected-agent UI reads that persisted timeline back as a live `Delegated work` feed.
- Creating an active project with an existing name reuses the existing Project Brain instead of creating another duplicate record.
- Assigned-agent project views collapse legacy same-name duplicate entries and prefer the record containing that agent's real delegated work.
- Projects can be viewed as native project cards rather than raw JSON.
- Users can rename a project, change its primary goal, and manually add project context, decisions, goals and milestones.
- `Show projects` opens a selectable project list with checkboxes and per-project Open controls.
- `Delete project` without a project name opens a selectable deletion list.
- Project deletion is approval-gated; selecting one or several projects creates one explicit deletion approval before Project Brain data is removed.
- Deleting a Project Brain does not silently erase historical agent chat messages.

Useful commands include:

```text
Show projects
Show project Church App
Rename project Church App to Shepherd
Set project Shepherd goal to Launch to ten churches
Add to project Shepherd context: Churches need WhatsApp onboarding
Add to project Shepherd decision: Use Supabase
Add to project Shepherd milestone: Finish onboarding
Delete project
Delete project Shepherd
```

### Agent instructions and local NPC brains
- Generated system instructions from agent identity, role, purpose and permissions.
- User-editable instructions with higher priority than learned defaults.
- Conversation-based preference learning without copying full chats into prompts.
- Learning audit with compact structured changes.
- Role-aware local NPC responses for common conversation and role-specific workflows.
- Local NPC job-title generation creates concise human-readable job titles without spending a provider call.
- Local-first routing avoids provider calls for supported deterministic tasks.

### Jobs, approvals and orchestration
- Multi-step background jobs with progress and provider-call budgets.
- Jobs keep their internal IDs for routing but show users human-readable NPC-generated titles in cards and job controls.
- Compound requests such as `research X, then create a PDF/DOCX` are planned as dependent steps: research completes first, then the existing local artifact generator creates the requested file without another provider call.
- Compound-job artifacts inherit the parent job's human NPC title as the document title and requested filename, so an internal section heading such as `Executive Summary` cannot become the artifact name.
- A research step with no usable sources is treated as failed; dependent artifact steps are blocked and no failure-message PDF/DOCX is generated.
- Deep research retries a small set of DDGS search backends instead of depending on a single `auto` backend; if all attempts fail, the real retrieval error is preserved in the failed research step so the user can see why no sources were found.
- Internal deep-research synthesis runs outside the owning persistent agent's normal conversation/NPC session, preventing chat preferences or local acknowledgement replies from replacing the gathered research report.
- Completed/failed background jobs emit a one-time user-visible completion event through the existing local event polling system.
- Background job ownership is preserved across agent switching: completion/file events are queued for the agent that started the job instead of being inserted into whichever agent chat happens to be open.
- Completed/failed/partial delegated team jobs also emit a one-time completion event; retrying a failed worker resets that notification marker so the retried result can alert again.
- Pause, resume and retry controls.
- Team jobs and handoffs between persistent agents.
- Persisted queued/working team handoffs are recovered after Agentie restarts; completed handoffs are not rerun.
- Project Brain work state is synchronized with team execution (`queued` → `working` → `completed` or `failed`) so recipient project views stay truthful.
- Live team-status questions such as `what's the state of that task?` ask active workers for short progress summaries without interrupting their work sessions.
- Team-status checks fall back to truthful backend state if a worker/provider cannot answer, rather than inventing progress.
- Collaboration avatars remain visible while a team job is active and for 60 seconds after terminal completion/failure.
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
- Professional DOCX, PDF, XLSX and PPTX artifacts that expose both a human document name and the downloadable filename.
- Word-export references such as `make docs file with this` are supported alongside `docx`, `doc file`, `word file` and `word document` wording.
- If exactly one eligible result exists in the active agent chat, a referenced artifact request creates the file directly.
- If several eligible research/results exist, Agentie returns a native result picker with a small single-select checkbox list so the user chooses the exact source instead of Agentie guessing.
- Result choices are isolated to the active agent/session; selecting a result passes a stable internal fingerprint back to the normal artifact generator.
- Error/fallback replies such as unresolved local-file messages and failed research messages are never eligible artifact sources.
- Creating the same artifact format from the same source result again returns the already-created file card instead of generating a duplicate file.

### Skills, plugins and MCP
- Real skill registry and role/skill routing infrastructure.
- Real MCP registration, discovery and tool execution through the MCP client.
- Global capability grants: approving a skill/MCP for all agents makes it available to existing and future agents by default.
- Per-agent overrides: an individual agent can still be explicitly blocked from a globally allowed capability.
- Consequential actions remain separately approval-gated even when the underlying skill/MCP is globally allowed.
- Connected MCP examples include Filesystem, Playwright, GitHub, Memory, Fetch, Time and Git when their real runtimes/dependencies are available.
- `Last30Days` now defaults to an Agentie-native Python 3.11+ implementation that searches separate recent-source lanes for Reddit, X, YouTube, Hacker News, GitHub and the wider web.
- Native Last30Days uses the exact gathered evidence for synthesis and citations, and falls back to a deterministic evidence summary if the configured AI provider is unavailable.
- The original `mvanhorn/last30days-skill` remains available as an optional upstream engine with its own Git/Python 3.12+ requirements.

Some service integrations still require credentials, provider setup or additional reliability work before they should be considered complete product integrations.

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
- Visible persistent pin/unpin controls in the agent sidebar
- Activity status dots while preserving the pinned-agent section above unpinned agents
- Agent chat
- Agent replies reuse that agent's existing round sidebar orb beside the response instead of rendering anonymous assistant text.
- Reply orbs visibly animate and show `Working` / `Queued` while a background job is active; terminal updates stop the animation for that job.
- When the selected specialist is still working or queued on delegated/team work, the chat shows one live `<agent> is working…` / `<agent> is queued…` row with that same orb so background work is not silent.
- If one agent finishes a background job while another agent is selected, the current chat gets only a small completion notice; the completion response and generated file remain queued for the owning agent's chat and appear when that agent is opened.
- Selected-agent `Delegated work` feed that polls persisted handoff tasks/results from that agent's own normal chat timeline
- Compact assigned-project previews plus an expandable full specialist project workspace
- Safe Markdown rendering for specialist results, including headings, lists, simple tables and fenced code blocks
- Native result-source picker cards for ambiguous DOCX/PDF/XLSX/PPTX creation requests
- Specialist project preview observers are idempotent and animation-frame debounced so rendering a project result cannot lock the browser in a self-triggering DOM mutation loop.
- Native agent profile cards instead of raw internal profile JSON
- Agent search/create controls
- Agent information/instructions editing
- Native cards for jobs and instructions
- Native Project Brain management cards and selectable project lists
- Approval UI
- Attachments
- Computer window/card
- Collapsible workspace panels
- Routines panel
- Skills/MCP catalog with global defaults and per-agent restrictions
- Native Last30Days result cards with source coverage and clickable evidence

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

Important core modules include `agent_registry.py`, `agent_prompt.py`, `npc_brain.py`, `job_engine.py`, `team_orchestrator.py`, `project_brain.py`, `result_memory.py`, `memory_store.py`, `advanced_local_router.py`, `agent_access.py`, `skill_registry.py`, `native_last30days.py`, `external_skill_runtime.py`, `capability_router.py`, `browser_automation.py`, and `computer_session.py`.

## Local-first execution philosophy

Agentie should not call a paid/remote model for work that can be handled safely and deterministically on-device.

The intended routing order is broadly:

1. Parse obvious native/local commands.
2. Use agent NPC/local intelligence for supported conversation and role behavior.
3. Use skills/plugins/tools when a capability is available.
4. Use a configured large model when genuine reasoning/generation is needed.
5. Use Browser/Computer execution when direct integrations are unavailable or insufficient.

Provider failure should therefore affect only work that genuinely requires that provider, not timers, local conversation, job controls, memory commands, or other supported local operations.

## Capability permission model

Agentie uses a layered permission model:

1. Global capability policy - the normal default after a user chooses **Always allow for all agents**.
2. Per-agent override - an agent can be explicitly allowed or blocked regardless of the global default.
3. Action-level approval - destructive, sending, posting or otherwise consequential tool actions can still require approval.

This means users do not need to approve the same safe tool separately for every agent, while sensitive agents can still be restricted.

## Last30Days

Agentie now includes a native Last30Days-compatible research engine that works on Python 3.11+ and is the default for normal `Last30Days ...` commands.

The native engine searches recent-source lanes for Reddit, X, YouTube, Hacker News, GitHub and the general web, de-duplicates evidence, synthesizes only from the gathered evidence, cites evidence IDs, and returns a dedicated research card. If the configured AI provider is unavailable, the gathered evidence is still returned as a deterministic summary rather than failing the whole skill.

Useful commands:

```text
Last30Days status
Last30Days AI coding agents
Last30Days what users want in AI assistants
```

The original upstream engine is still optional:

```text
Install Last30Days skill
Update Last30Days skill
```

That optional upstream runtime is installed into `workspace/external_skills/last30days-skill` and currently requires Python 3.12+. Agentie's native implementation does not require that runtime.

## Run locally

Python 3.10+ is required. Python 3.11 is currently used during development. Some optional external skills may require newer runtimes independently.

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

For a new feature, run its targeted regression file first, then run the related subsystem tests, then the full suite, and finally perform the manual UI/workflow test in Agentie.

## Development rules

When extending Agentie:

1. Inspect existing functionality and the relevant repo architecture before adding new code.
2. Do not duplicate an existing subsystem, state store, router, permission model or UI implementation.
3. Prefer the smallest safe patch over broad rewrites and connect new behavior to the existing source of truth.
4. Preserve backend/API contracts during UI-only changes.
5. Keep local operations local where possible.
6. Require approvals for consequential/irreversible operations.
7. Preserve per-agent memory and project-context isolation.
8. Add regression tests for every new feature or meaningful bug fix.
9. Run targeted tests, related subsystem tests and the full regression suite before considering a feature complete.
10. Keep this README updated as major capabilities are added.

## Current development roadmap

### 1. Skills and plugin permissions - active
Continue hardening real external skill/MCP discovery, credentials, health checks and permission UX. Global defaults + per-agent restrictions are now implemented, and Last30Days now has a native Python 3.11+ runtime.

### 2. Background/routine reliability - next
Harden scheduled work, restart recovery, missed-run behavior, job continuation and failure recovery.

### 3. Voice
Turn the microphone UI into a complete speech-input workflow and later support richer voice interaction.

### 4. Integration hardening
Finish end-user connection and reliability flows for services such as GitHub, Gmail, Calendar, Slack and Notion.

### 5. Authentication/accounts
Add production user/account isolation if Agentie moves from a local personal workspace into a multi-user product.

### 6. Final UI/UX polish
Once the underlying capabilities are stable, finish the cohesive desktop/web experience around those stable contracts.

### 7. Computer reliability and autonomy - later
Return to WSL/KasmVNC reliability, Browser/Computer fallback, observe-act-verify autonomy and visual task execution after the other core systems are stable.

## Status

Agentie v2 is under active development. It already has a substantial working agent runtime; the current focus is making that runtime more autonomous, local-first, reliable and capable before treating the UI as final.
