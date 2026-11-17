"""The provider of each profile (specification, section 5, "Profiles")."""

from utux.errors import ModelProviderConfigError
from utux.interfaces.model_provider import ModelProvider
from utux.providers.openai_compatible import OpenAICompatibleProvider, openrouter

OLLAMA_BASE_URL = "http://localhost:11434/v1"
PROFILES = ("default", "local")


def provider_for_profile(profile: str) -> ModelProvider:
    """Return the model provider of a profile.

    `default` is OpenRouter. `local` is a local OpenAI-compatible server at
    Ollama's usual address, which needs no key.

    Raises:
        ModelProviderConfigError: If the profile is not known, or its
            provider cannot be created.
    """
    if profile == "default":
        return openrouter()
    if profile == "local":
        return OpenAICompatibleProvider(name="ollama", base_url=OLLAMA_BASE_URL, api_key_env=None)
    raise ModelProviderConfigError(
        f"the profile {profile} has no provider; known profiles: {', '.join(PROFILES)}"
    )
