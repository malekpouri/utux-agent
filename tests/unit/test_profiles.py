"""M0-11: the provider of each profile."""

import pytest

from utux.errors import ModelProviderConfigError
from utux.providers import profiles


def test_default_profile_is_openrouter() -> None:
    provider = profiles.provider_for_profile("default")
    assert provider.name == "openrouter"
    assert provider.is_external is True


def test_local_profile_is_a_local_openai_compatible_server() -> None:
    provider = profiles.provider_for_profile("local")
    assert provider.name == "ollama"
    assert provider.is_external is False


def test_unknown_profile_is_a_configuration_error() -> None:
    with pytest.raises(ModelProviderConfigError, match="synthetic-profile"):
        profiles.provider_for_profile("synthetic-profile")


def test_local_profile_uses_the_configured_address() -> None:
    provider = profiles.provider_for_profile("local", local_base_url="http://127.0.0.1:8080/v1")
    assert provider.name == "ollama"
    assert provider.is_external is False


def test_a_local_profile_pointed_at_another_host_is_external() -> None:
    # is_external is derived from the host, not from the profile's name.
    provider = profiles.provider_for_profile(
        "local", local_base_url="https://models.example.org/v1"
    )
    assert provider.is_external is True


def test_the_default_address_is_ollamas() -> None:
    assert profiles.OLLAMA_BASE_URL == "http://localhost:11434/v1"
