import os

from agents import AsyncOpenAI, OpenAIChatCompletionsModel, set_tracing_disabled
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_LOCAL_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_LOCAL_MODEL = "gemma4"
DEFAULT_OPENROUTER_MODEL = "openrouter/auto"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def _provider() -> str:
    """Resolve the configured powerful/cloud provider."""
    configured = os.getenv("AGENTIE_PROVIDER", "").strip().lower()
    if configured in {"google", "google_ai", "google-ai", "gemini", "google_ai_studio"}:
        return "gemini"
    if configured in {"openrouter", "open_router"}:
        return "openrouter"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        if not os.getenv("OPENROUTER_API_KEY"):
            return "gemini"
    return "openrouter"


def get_provider_info(tier: str = "powerful") -> dict[str, str]:
    selected = str(tier or "powerful").strip().lower()
    if selected == "local":
        return {
            "provider": "local",
            "tier": "local",
            "model": os.getenv("AGENTIE_LOCAL_MODEL", DEFAULT_LOCAL_MODEL).strip() or DEFAULT_LOCAL_MODEL,
            "base_url": os.getenv("AGENTIE_LOCAL_BASE_URL", DEFAULT_LOCAL_BASE_URL).strip().rstrip("/") or DEFAULT_LOCAL_BASE_URL,
        }
    provider = _provider()
    if provider == "gemini":
        return {
            "provider": "gemini",
            "tier": "powerful",
            "model": os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            "base_url": GEMINI_OPENAI_BASE_URL,
        }
    return {
        "provider": "openrouter",
        "tier": "powerful",
        "model": os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
        "base_url": OPENROUTER_BASE_URL,
    }


def get_model(provider_info: dict[str, str] | None = None) -> OpenAIChatCompletionsModel:
    """Build a model from Agentie's selected local or powerful provider."""
    info = provider_info or get_provider_info()
    provider = info["provider"]

    if provider == "local":
        # Ollama and other OpenAI-compatible local runtimes do not require a real
        # cloud secret. A configurable placeholder keeps this compatible with
        # runtimes that validate the Authorization header syntactically.
        api_key = os.getenv("AGENTIE_LOCAL_API_KEY", "agentie-local")
        client = AsyncOpenAI(api_key=api_key, base_url=info.get("base_url") or DEFAULT_LOCAL_BASE_URL)
    elif provider == "gemini":
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is not set")
        client = AsyncOpenAI(api_key=api_key, base_url=GEMINI_OPENAI_BASE_URL)
    else:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        app_url = os.getenv("AGENTIE_APP_URL", "http://localhost:8000")
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": app_url,
                "X-OpenRouter-Title": "Agentie",
            },
        )

    set_tracing_disabled(True)
    return OpenAIChatCompletionsModel(model=info["model"], openai_client=client)
