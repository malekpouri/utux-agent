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
