import os

from agents import AsyncOpenAI, OpenAIChatCompletionsModel, set_tracing_disabled
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_OPENROUTER_MODEL = "openrouter/auto"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def _provider() -> str:
    """Resolve the configured paid-model provider without affecting local-first routing."""
    configured = os.getenv("AGENTIE_PROVIDER", "").strip().lower()
    if configured in {"google", "google_ai", "google-ai", "gemini", "google_ai_studio"}:
        return "gemini"
    if configured in {"openrouter", "open_router"}:
        return "openrouter"
    # Friendly auto-detection: a Gemini-only installation should work without another flag.
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        if not os.getenv("OPENROUTER_API_KEY"):
            return "gemini"
    return "openrouter"


def get_provider_info() -> dict[str, str]:
    provider = _provider()
    if provider == "gemini":
        return {
            "provider": "gemini",
            "model": os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
            "base_url": GEMINI_OPENAI_BASE_URL,
        }
    return {
        "provider": "openrouter",
        "model": os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
        "base_url": OPENROUTER_BASE_URL,
    }


def get_model() -> OpenAIChatCompletionsModel:
    """Build Agentie's model through the selected OpenAI-compatible provider."""
    info = get_provider_info()
    provider = info["provider"]

    if provider == "gemini":
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

    # Agentie owns its provider-independent observability layer. OpenAI SDK tracing
    # would require a separate OpenAI Platform key, so keep it disabled here.
    set_tracing_disabled(True)
    return OpenAIChatCompletionsModel(model=info["model"], openai_client=client)
