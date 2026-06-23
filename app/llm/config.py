"""LLM configuration: which provider/model to use and where the API key comes from.

Values are read from the environment (loaded from a ``.env`` file), never
hardcoded. The rest of the app depends on the ``LLMConfig`` object -- not on raw
environment variables or a specific provider -- which is the seam that keeps the
LLM client provider-agnostic.
"""

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Which environment variable holds the API key, per provider.
_API_KEY_ENV_VAR = {
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL = "llama-3.3-70b-versatile"


@dataclass(frozen=True)
class LLMConfig:
    """Resolved LLM settings for one run.

    Frozen (immutable) so config can't be changed accidentally after load. The
    ``api_key`` is excluded from ``repr`` so it can't leak into logs or tracebacks.
    """

    provider: str
    model: str
    api_key: str = field(repr=False)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """Build config from environment variables, loading ``.env`` first.

        Raises ``ValueError`` for an unknown provider and ``RuntimeError`` if the
        provider's API key is not set -- both with messages that say how to fix it.
        """
        load_dotenv()  # read .env into the environment (a no-op if the file is absent)

        provider = os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER).lower()
        model = os.getenv("LLM_MODEL", DEFAULT_MODEL)

        key_var = _API_KEY_ENV_VAR.get(provider)
        if key_var is None:
            known = ", ".join(sorted(_API_KEY_ENV_VAR))
            raise ValueError(
                f"Unknown LLM_PROVIDER {provider!r}. Known providers: {known}."
            )

        api_key = os.getenv(key_var)
        if not api_key:
            raise RuntimeError(
                f"Missing API key: set {key_var} in your .env file (LLM_PROVIDER={provider!r})."
            )

        return cls(provider=provider, model=model, api_key=api_key)
