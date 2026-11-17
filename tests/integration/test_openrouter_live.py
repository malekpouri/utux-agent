"""M0-10: a live smoke test against OpenRouter.

It needs `OPENROUTER_API_KEY` and network access, and costs a fraction of a
cent. It is marked `live`, so it runs only with `uv run pytest -m live`, and
it is skipped without the key. The model can be chosen with
`UTUX_LIVE_OPENROUTER_MODEL`.
"""

import os

import pytest

from utux.interfaces.model_provider import FinishReason, Message, MessageRole, ModelRequest
from utux.providers.openai_compatible import openrouter

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    not os.environ.get("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY is not set"
)
def test_one_short_call_reports_usage_and_cost() -> None:
    model = os.environ.get("UTUX_LIVE_OPENROUTER_MODEL", "openai/gpt-4o-mini")
    answer = openrouter().complete(
        ModelRequest(
            model=model,
            messages=(Message(role=MessageRole.USER, content="Reply with the word: ready"),),
            timeout_seconds=60.0,
            temperature=0.0,
            max_output_tokens=8,
        )
    )
    assert answer.usage.tokens_in > 0
    assert answer.usage.tokens_out > 0
    assert answer.finish_reason in (FinishReason.STOP, FinishReason.LENGTH)
    # This is the field the synthetic fixtures could not confirm.
    assert answer.cost_usd is not None, "OpenRouter did not report usage.cost"
