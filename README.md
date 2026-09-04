# Agentie v2

Agentie is a local-first multi-agent workspace for creating persistent AI employees that can remember, delegate, collaborate, use tools, run scheduled work, browse the web, and operate a persistent Linux Company Computer.

The backend is Python/FastAPI with a lightweight web UI. Agentie prefers deterministic and local execution when possible and can automatically route reasoning-heavy work to a configured powerful model.

## Core product model

Agentie is designed as an AI company rather than a collection of isolated chats. Persistent agents can have a name, avatar, role, personality, goal, responsibilities, instructions, memory, tools, skills, permissions, project context, and relationships with other agents.

Current systems include:

- persistent named agents and per-agent chat/memory isolation
- generated and user-editable agent instructions
- learned communication preferences
- manager / Chief-of-Staff delegation
- agent-to-agent handoffs and group work
- Project Brain shared project context with bounded specialist handoffs
- background jobs, retries, approvals, routines and activity traces
- local utilities, files, documents, research, code execution and artifacts
- skills, MCP integrations and capability permissions
- automatic Local / Auto / Powerful model routing
- browser automation and Teach by Demonstration
- a persistent shared Company Computer

## Projects / Project Brain

Project Brain stores durable goals, decisions, milestones, artifacts, handoffs and distilled shared context for long-running work. Specialists receive role-scoped project briefs instead of another agent's private conversation history.

Useful commands include:

```text
Show projects
Show project Church App
Rename project Church App to Shepherd
Set project Shepherd goal to Launch to ten churches
Add to project Shepherd context: Churches need WhatsApp onboarding
Add to project Shepherd decision: Use Supabase
Add to project Shepherd milestone: Finish onboarding
Delete project Shepherd
```

Project deletion and other irreversible operations use Agentie's approval flow.

## Jobs, collaboration and manager autonomy

Agentie supports persisted team jobs, manager-led decomposition, specialist selection, sequential or parallel delegation, bounded handoffs, failure recovery, user-visible status and completion events.

The manager layer is local-first where possible: routing and task selection do not need to spend a provider call simply to decide which existing employee should handle a job.

## Memory

Agentie has persistent user and agent memory, semantic retrieval, explicit `Remember that...` commands, learned preferences, and per-agent isolation. Shared project/company knowledge is promoted deliberately rather than silently copying every employee's private chat into every other employee's context.

## Skills, plugins and MCP

Agentie includes a real skill registry and MCP client. Capabilities can be allowed globally, restricted per agent, and still require a separate action-level approval for consequential behavior.

Examples include Filesystem, Playwright, GitHub, Memory, Fetch, Time, Git, Google Workspace and other MCP-compatible services when their actual runtimes and credentials are configured.

## Telegram channel

Telegram is available as a native two-way channel in **Plugins → Channels**. Each local Agentie user supplies a bot token created with [BotFather](https://t.me/BotFather), then pairs one private Telegram account with a short-lived, one-time code. Bot tokens are encrypted in the local workspace and are never returned by the API or shown again after saving.

Start Agentie, open Plugins, add Telegram, save the BotFather token, and choose **Generate pairing code**. Open the bot in a private Telegram chat and send that code. Normal language is the primary interface; these shortcuts are also available:

```text
/manager
/agent Ben
/agent
/status
/routines
/approvals
```

Agentie uses Telegram long polling, so a public callback URL is not required. Approval buttons resolve through Agentie's existing approval store. Approving in Telegram does not grant broader permissions, and real-money or other consequential actions still require an explicit approval. Use **Disconnect** to unpair the account or **Remove token** to delete the encrypted credential and stop the channel.

## Teach by Demonstration

Agentie can record browser workflows performed in the visible Chromium session inside the Company Computer, turn the recorded actions into reusable workflow skills, and replay them through the same browser executor.

Passwords are not persisted in taught workflows. Sensitive steps remain user-controlled. Arbitrary non-browser desktop workflow teaching is a later extension; current non-browser desktop control is an execution layer rather than a recorder.

Useful commands include:

```text
Teach Agentie: publish weekly update
Stop teaching
Cancel teaching
Show taught workflows
Show workflow publish weekly update
Run workflow publish weekly update
Delete workflow publish weekly update
```

## Agentie Company Computer

Agentie's Computer is one persistent user-scoped Linux computer shared by the user's AI employees. It is implemented with **QEMU**, not a host desktop wrapper.

### Runtime

- QEMU virtual machine
- persistent `QCOW2` disk at `workspace/company_computer/company-computer.qcow2`
- normal Debian `generic` image with the standard kernel for broad device compatibility
- Openbox lightweight window manager
- Chromium with a persistent profile
- PCManFM file manager
- xterm terminal
- QEMU Guest Agent for controlled guest operations and file transfer
- QMP for VM lifecycle/input control
- QEMU's native VNC WebSocket display with local noVNC assets for the existing embedded Computer card

There is no WSL, XFCE, KasmVNC or port-8444 fallback in the Company Computer runtime.

### Hardware acceleration

Agentie selects the native accelerator for the host:

| Host | Accelerator |
| --- | --- |
| Windows | WHPX / Windows Hypervisor Platform |
| macOS | HVF |
| Linux | KVM |

Agentie does **not** silently fall back to slow software emulation. TCG compatibility mode is available only when the user explicitly enables `AGENTIE_QEMU_ALLOW_TCG=1`.

If hardware virtualization is unavailable, the Computer surfaces an actionable error instead of pretending that it started successfully.

### Resource scaling

The Company Computer sizes itself from host RAM/CPU. The practical low-end Chromium profile is approximately 1 GB RAM and 1 vCPU. More capable hosts receive a larger VM profile. The shared VM can suspend after inactivity so its CPU/RAM footprint is released while the persistent disk remains intact.

Default idle suspension is controlled by:

```text
AGENTIE_COMPUTER_IDLE_SECONDS=600
```

### Persistence

The same QCOW2 disk preserves:

- Chromium profile, cookies and authenticated browser state
- browser tabs/session restoration where Chromium supports it
- downloaded files
- files created by agents or the user
- installed guest applications
- desktop and application settings
- working directories and other guest filesystem state

Stopping Agentie, restarting the host, or suspending/resuming the Company Computer does not intentionally replace that disk.

### Shared control and human takeover

The Company Computer has one authoritative controller at a time. Its persisted state machine includes:

```text
STOPPED
STARTING
READY
AGENT_CONTROL
USER_REQUIRED
USER_CONTROL
IDLE
SUSPENDED
ERROR
```

An agent can hold control, explicitly hand the computer to another agent, or pause for the user. Login credentials, password fields, CAPTCHA, passkeys, security keys, 2FA and identity-verification pages trigger user takeover.

Human takeover keeps the **same VM, same Chromium profile, same tab and same session** alive. After the user finishes the required action, **Continue Agent** gives control back to the paused employee.

### Browser automation

Playwright connects to Chromium **inside the QEMU guest** over a local forwarded CDP port. Agentie does not launch a separate hidden host browser as a fallback for Company Computer work.

Consequential browser actions continue through the existing approval system.

### Guest Terminal and applications

Commands such as:

```text
Run pwd in the terminal
Computer terminal: ls -la
Open terminal in the computer
Open file manager in the computer
Open Chromium in the computer
Install inkscape on the computer
```

execute against the real persistent guest. Ordinary commands run as the unprivileged `agentie` user. Package installation, persistent system changes, destructive commands and detected external-write commands require Agentie's approval before execution.

An explicit legacy `Desktop control: terminal ...` path remains a deliberately restricted host-workspace inspection helper; it does not expose an arbitrary host shell. Normal agent terminal work routes to the Company Computer guest.

### Non-browser desktop control

For applications outside Chromium, Agentie has a separate guest-display input layer. It can perform controlled mouse, keyboard and scrolling operations against the actual X display using the guest automation component rather than creating a fake desktop or a second browser.

Examples:

```text
Company Computer control: click at 420, 240
Company Computer control: type focused: hello world
Company Computer control: press Enter
Company Computer control: scroll down 4
```

### Host ↔ guest file transfer

Agentie transfers files through the QEMU Guest Agent. Transfers are confined to the Agentie host workspace and `/home/agentie` inside the guest, with a 100 MB per-file limit.

Examples:

```text
Copy report.pdf to the computer
Download /home/agentie/Agentie Exports/result.txt from the computer
```

Default guest transfer folders are:

```text
/home/agentie/Agentie Inbox
/home/agentie/Agentie Exports
```

## Browser and research

Agentie includes browser interaction, screenshots, monitoring, deep research, citation verification, teachable browser workflows, and Company Computer fallback when a direct integration is not available.

## Local-first model routing

Agentie should not spend a remote model call for work that can be handled safely and deterministically on-device.

The intended routing order is broadly:

1. parse native/local commands
2. use local agent/NPC behavior where appropriate
3. use skills, plugins and tools
4. reuse deterministic taught workflows
5. call a configured powerful model when genuine reasoning/generation is needed
6. use Browser / Company Computer execution when direct integrations are unavailable or insufficient

Routing modes are:

- `Local` — never silently falls back to cloud
- `Auto` — prefers local execution/model and escalates complex work automatically
- `Powerful` — explicitly uses the configured cloud/powerful model

## Approval model

Agentie uses layered permissions:

1. global capability policy
2. per-agent capability override
3. action-level approval for consequential operations

The Company Computer extends the same model rather than creating a separate security system. Sending/posting, destructive operations, persistent system changes and similar actions can therefore pause on the standard Agentie approval card.

## Web UI

The UI includes persistent agent switching, avatars/activity state, group chats, agent profiles/instructions, Project Brain views, job cards, approvals, attachments, routines, skills/plugins, model routing and the embedded Computer card.

The Computer card preserves the existing window experience: embedded view, minimize, fullscreen/maximize, stop, mouse/keyboard interaction and user takeover controls.

## Architecture

```text
agentie-v2/
├── agentie/
│   ├── agents/
│   ├── core/
│   │   ├── company_computer.py
│   │   ├── company_computer_commands.py
│   │   ├── company_computer_desktop.py
│   │   ├── company_computer_files.py
│   │   ├── company_computer_idle.py
│   │   ├── browser_automation.py
│   │   ├── browser_monitor.py
│   │   ├── agent_registry.py
│   │   ├── agent_prompt.py
│   │   ├── memory_store.py
│   │   ├── project_brain.py
│   │   ├── team_orchestrator.py
│   │   ├── manager_autopilot.py
│   │   └── ...
│   ├── models/
│   └── tools/
├── frontend/
├── tests/
├── workspace/
├── main.py
└── pyproject.toml
```

## Run locally

Python 3.10+ is required. Python 3.11 is the primary development runtime.

```powershell
cd C:\Users\user\agentie-v2
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python main.py
```

Create `.env` from `.env.example` and configure the model/provider settings you want. Never commit real API keys or secrets.

On first Company Computer use, Agentie locates or prepares QEMU and the guest image/runtime. The host must support the appropriate virtualization accelerator (WHPX, HVF or KVM).

## Tests

Run the complete regression suite after every meaningful change:

```powershell
python -m unittest discover -s tests -p "test_*regression.py" -v
```

Company Computer regressions cover accelerator selection, explicit compatibility mode, QCOW2 persistence, resource sizing, lifecycle and ownership, takeover, browser integration, idle suspension, file transfer, guest commands, approval gating, non-browser desktop input and frontend integration.

A GitHub Actions regression workflow also runs the same suite on pushes to `main11` when repository Actions are enabled.

## Development rules

When extending Agentie:

1. inspect the existing implementation before adding another subsystem
2. do not duplicate state stores, routers, permission models or UI unnecessarily
3. preserve working functionality and backend contracts
4. keep local operations local when possible
5. require approval for consequential or irreversible operations
6. preserve agent-memory and project-context isolation
7. do not expose fake tools, placeholder integrations or simulated runtime capabilities
8. add regression tests for every meaningful feature/change
9. run targeted tests, related subsystem tests and the full regression suite
10. keep major runtime documentation current

## Current roadmap

### Durable execution
Continue moving long-running jobs/routines from process-local workers toward durable restart-safe execution.

### Company Computer autonomy
Harden visual observe-act-verify behavior, resilient application interaction, desktop teaching, session recovery and multi-step user/agent handoff on top of the QEMU Company Computer.

### Approval policy engine
Expand action policies from one-time approval into richer per-agent/tool/action rules while preserving explicit approval for sensitive operations.

### Integrations
Continue hardening real end-user connections for services such as GitHub, Gmail, Calendar, Slack, Notion and messaging platforms.

### Authentication/accounts
Add production account isolation if Agentie evolves from a local personal workspace into a hosted multi-user product.

## Status

Agentie v2 is under active development. The Company Computer is designed as a persistent, shared QEMU execution environment while Agentie's broader runtime remains local-first, provider-efficient and approval-aware.
