# Agentie v2

Agentie v2 is a clean Python-first rebuild of Agentie using FastAPI and the OpenAI Agents SDK. The first milestone uses OpenRouter through its OpenAI-compatible Chat Completions API so the agent model can be changed without rewriting the runtime.

## Current milestone

- FastAPI service
- OpenAI Agents SDK runtime
- OpenRouter-compatible model provider
- Configurable model via `OPENROUTER_MODEL`
- First Agentie assistant
- First Python function tool: current UTC time
- `/health` readiness endpoint
- `/agent/run` agent execution endpoint

## Project structure

```text
agentie-v2/
├── agentie/
│   ├── agents/
│   │   └── assistant.py
│   ├── core/
│   │   └── runner.py
│   ├── models/
│   │   └── provider.py
│   └── tools/
│       └── basic_tools.py
├── .env.example
├── .gitignore
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

Create a local `.env` from `.env.example` and set your OpenRouter key:

```env
OPENROUTER_API_KEY=your_key_here
OPENROUTER_MODEL=openrouter/auto
AGENTIE_APP_URL=http://localhost:8000
PORT=8000
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

Test the first agent and force a tool-use example:

```bash
curl -X POST http://localhost:8000/agent/run \
  -H "Content-Type: application/json" \
  -d '{"message":"What is the current UTC time? Use your time tool."}'
```

Expected response shape:

```json
{
  "result": "..."
}
```

## Next milestones

1. Conversation sessions and persistent memory with Supabase.
2. Agent creation and stored agent identities/instructions.
3. Approval gates for consequential tools.
4. Skills and plugin/MCP registry.
5. Multiple agents, delegation, and handoffs.
6. Browser/computer tools in isolated sandboxes.
7. Background and scheduled tasks.
8. Agentie web/mobile/desktop clients.
