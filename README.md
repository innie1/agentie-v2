# Agentie v2

Agentie v2 is a clean Python-first rebuild of Agentie using FastAPI and the OpenAI Agents SDK. The runtime is local-first, with OpenRouter-compatible model routing, persistent agent features, and a real Linux Computer powered by WSL Ubuntu, XFCE, and KasmVNC.

## Current milestone

- FastAPI service and agent runtime
- OpenRouter-compatible model provider
- Configurable model via `OPENROUTER_MODEL`
- Agent creation, roles, memory, routines, plugins/MCP, skills, observability, browser tooling, and local artifacts
- Real Agentie Computer: WSL Ubuntu + XFCE + KasmVNC
- Embedded and fullscreen Computer views with mouse/keyboard interaction
- Windows-style Computer window controls and resize/reconnect handling
- Controlled Agent ↔ Linux bridge for terminal commands and Linux workspace files
- `/health` readiness endpoint
- `/agent/run` agent execution endpoint

## Agentie Computer

The Computer uses the WSL distribution configured by `AGENTIE_WSL_DISTRO` (default: `Ubuntu`). The visible desktop runs through KasmVNC and remains separate from Agentie's restricted local Python executor.

Agent-controlled Linux terminal commands run inside:

```text
~/AgentieWorkspace
```

Useful chat commands include:

```text
Run pwd in the Linux terminal
Run git status in the Linux terminal
Show Linux files
Read Linux file docs/notes.txt
```

The bridge deliberately rejects destructive/system-level commands such as `sudo`, recursive forced deletion, filesystem formatting, shutdown/reboot, and writes into protected system directories. Those actions must be performed manually in the visible Linux Terminal.

## Project structure

```text
agentie-v2/
├── agentie/
│   ├── agents/
│   ├── core/
│   │   ├── desktop_runtime.py
│   │   ├── wsl_desktop.py
│   │   ├── wsl_bridge.py
│   │   └── runner.py
│   ├── models/
│   └── tools/
├── frontend/
├── scripts/
├── tests/
├── .env.example
├── main.py
├── pyproject.toml
└── README.md
```

## Run locally

Python 3.10+ is required.

```bash
python -m venv .venv
```

Activate the environment.

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

Install the project:

```bash
pip install -e .
```

Create a local `.env` from `.env.example` and configure the provider:

```env
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=openrouter/auto
AGENTIE_APP_URL=http://localhost:8000
PORT=8000
AGENTIE_WSL_DISTRO=Ubuntu
```

Never commit your real `.env` file or API key.

Start Agentie:

```bash
python main.py
```

Check readiness:

```bash
curl http://localhost:8000/health
```

Run tests:

```bash
python -m unittest discover -s tests
```

## Next milestones

1. Expose Linux file writes/edits as first-class agent tools with approval gates where needed.
2. Shared upload/download flow between Agentie chat and `~/AgentieWorkspace`.
3. Linux screenshots and computer activity trace entries.
4. App launching and browser-open actions through the Computer bridge.
5. Per-agent persistent Linux workspaces and stronger process isolation.
6. Automatic Computer health recovery for XFCE/KasmVNC failures.
