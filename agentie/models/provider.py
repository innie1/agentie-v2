import os

from agents import AsyncOpenAI, OpenAIChatCompletionsModel, set_tracing_disabled
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/auto"


def get_model() -> OpenAIChatCompletionsModel:
    """Build the model used by Agentie through OpenRouter's OpenAI-compatible API."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    model_name = os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
    app_url = os.getenv("AGENTIE_APP_URL", "http://localhost:8000")

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": app_url,
            "X-OpenRouter-Title": "Agentie",
        },
    )

    # OpenAI tracing requires an OpenAI Platform key. Agentie currently routes
    # model calls through OpenRouter, so tracing is disabled for this first build.
    set_tracing_disabled(True)

    return OpenAIChatCompletionsModel(
        model=model_name,
        openai_client=client,
    )
