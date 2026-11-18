"""The provider of each profile (specification, section 5, "Profiles")."""

from utux.errors import ModelProviderConfigError
from utux.interfaces.model_provider import ModelProvider
from utux.providers.openai_compatible import OpenAICompatibleProvider, openrouter

OLLAMA_BASE_URL = "http://localhost:11434/v1"
PROFILES = ("default", "local")


def provider_for_profile(profile: str, *, local_base_url: str = OLLAMA_BASE_URL) -> ModelProvider:
    """Return the model provider of a profile.

    `default` is OpenRouter. `local` is an OpenAI-compatible server at
    `local_base_url`, `local_server.base_url` in `utux.yaml`, which needs no
    key. Whether it is external is derived from the host of that address,
    as for every provider: a server on another machine is external.

    Raises:
        ModelProviderConfigError: If the profile is not known, or its
            provider cannot be created.
    """
    if profile == "default":
        return openrouter()
    if profile == "local":
        return OpenAICompatibleProvider(name="ollama", base_url=local_base_url, api_key_env=None)
    raise ModelProviderConfigError(
        f"the profile {profile} has no provider; known profiles: {', '.join(PROFILES)}"
    )
