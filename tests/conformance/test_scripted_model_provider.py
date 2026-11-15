"""M0-09: the scripted fake provider passes the `ModelProvider` conformance suite."""

from model_provider_suite import Failure, ModelProviderConformance

from utux.errors import ModelAuthenticationError, ModelRateLimitError
from utux.interfaces.model_provider import ModelProvider
from utux.providers.scripted import (
    ScriptedFailure,
    ScriptedModelProvider,
    ScriptedRawReply,
    ScriptedReply,
    ScriptedStep,
)


class TestScriptedModelProvider(ModelProviderConformance):
    def make_replying(self, replies: int) -> ModelProvider:
        return ScriptedModelProvider(
            [ScriptedReply(content=f"synthetic reply {n}", cost_usd=0.001) for n in range(replies)]
        )

    def make_without_cost(self) -> ModelProvider:
        return ScriptedModelProvider([ScriptedReply(content="synthetic reply", cost_usd=None)])

    def make_failing(self, failure: Failure) -> ModelProvider:
        steps: dict[Failure, ScriptedStep] = {
            Failure.AUTHENTICATION: ScriptedFailure(ModelAuthenticationError("synthetic failure")),
            Failure.RATE_LIMIT: ScriptedFailure(ModelRateLimitError("synthetic failure")),
            # An upstream answer without usage is not a valid response.
            Failure.INVALID_RESPONSE: ScriptedRawReply(
                {"model": "synthetic/model", "content": "synthetic", "finish_reason": "stop"}
            ),
        }
        return ScriptedModelProvider([steps[failure]])

    def make_slow(self, delay_seconds: float) -> ModelProvider:
        return ScriptedModelProvider(
            [ScriptedReply(content="synthetic reply", delay_seconds=delay_seconds)]
        )
