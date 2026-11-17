"""M0-10: the OpenAI-compatible client passes the `ModelProvider` conformance suite.

The responses are synthetic and hand-written (tests/fixtures/openai_compatible).
"""

import sys
from pathlib import Path

import pytest
from model_provider_suite import Failure, ModelProviderConformance

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unit"))

from provider_fakes import (  # noqa: E402
    OK_WITH_COST,
    OK_WITHOUT_COST,
    SYNTHETIC_KEY,
    ScriptedTransport,
    response,
)

from utux.interfaces.model_provider import ModelProvider  # noqa: E402
from utux.providers.openai_compatible import openrouter  # noqa: E402

FAILURES = {
    Failure.AUTHENTICATION: response(401, "error_unauthorized.json"),
    Failure.RATE_LIMIT: response(429, "error_rate_limited.json"),
    Failure.INVALID_RESPONSE: response(200, "completion_without_usage.json"),
    Failure.UNAVAILABLE: response(503, "error_unavailable.json"),
    Failure.REQUEST_REJECTED: response(400, "error_bad_request.json"),
}


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", SYNTHETIC_KEY)


class TestOpenRouterProvider(ModelProviderConformance):
    def make_replying(self, replies: int) -> ModelProvider:
        return openrouter(transport=ScriptedTransport(OK_WITH_COST))

    def make_without_cost(self) -> ModelProvider:
        return openrouter(transport=ScriptedTransport(OK_WITHOUT_COST))

    def make_failing(self, failure: Failure) -> ModelProvider:
        # Retries are part of the client; they must not slow the suite down.
        return openrouter(transport=ScriptedTransport(FAILURES[failure]), sleep=lambda _: None)

    def make_slow(self, delay_seconds: float) -> ModelProvider:
        return openrouter(transport=ScriptedTransport(OK_WITH_COST, delay_seconds=delay_seconds))
