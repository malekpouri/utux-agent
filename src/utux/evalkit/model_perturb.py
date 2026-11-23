"""Model-written perturbations with Gemini, under a cost cap (M0-15c, ADR-0019).

Gemini writes four types of perturbation (direction, causal, overgeneralisation,
missing comparator) and checks each one in a separate call that only flags
disagreement. It never gives a label: the label follows from the type, as for
the rule-made types (`utux.evalkit.perturb`). An item whose check disagrees,
or whose answers are not clean, is dropped and counted; the others get
`confirmation: model_check`.

Access follows ADR-0019, a scoped exception to ADR-0008 for gold tooling
only:

- Gemini is reached through the standard-library OpenAI-compatible client,
  with the key read only from `GEMINI_API_KEY`.
- Every call is a `model_call` event. Its `cost_usd` is what the provider
  reports, which for Gemini is nothing; the table price goes only into
  `data.estimated_cost_usd`, an estimate.
- The cap prices every token at the table's higher price, whatever the day,
  and refuses a call that could pass it.
"""

import json
import random
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from importlib.resources import files

from utux.errors import ModelAuthenticationError, ModelProviderError, UtuxError
from utux.evalkit.gold import Confirmation, Domain, GoldItem
from utux.evalkit.perturb import (
    MODEL_TYPES,
    PerturbationRun,
    PerturbationType,
    Skip,
    evidence_text,
    is_parent,
    make_child,
)
from utux.events.log import EventLog
from utux.interfaces.model_provider import (
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
from utux.providers.openai_compatible import OpenAICompatibleProvider, Transport
from utux.schemas.event import EventStatus, EventType, NewEvent
from utux.workspace.model_calls import REFUSED_BUDGET, input_hash, output_hash, status_reason

GEMINI_MODEL = "gemini-3.8-flash"
"""Pinned in the gold v0 strategy, section 7."""
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_KEY_VARIABLE = "GEMINI_API_KEY"
PROVIDER_NAME = "gemini"
ACTOR = "system:utux"

PRICE_SOURCE = "https://aistudio.google.com/docs/pricing"
PRICE_RETRIEVED = "2026-11-23"


@dataclass(frozen=True)
class Price:
    """US dollars per million tokens, paid tier, standard, from `first_day` on."""

    first_day: date
    input_per_million: float
    output_per_million: float


PRICES = (
    Price(date(2026, 1, 1), 0.75, 3.75),
    Price(date(2027, 1, 1), 1.50, 7.50),
)
"""`gemini-3.8-flash` on the Gemini API pricing page (`PRICE_SOURCE`, read
`PRICE_RETRIEVED`). Output includes thinking tokens."""

CAP_PRICE = Price(date(2026, 1, 1), 1.50, 7.50)
"""The higher price, used by the cap on every day (ADR-0019)."""

WRITER_PROMPT = "perturb-writer@1"
CHECK_PROMPT = "perturb-check@1"
MAX_OUTPUT_TOKENS = 2048
TIMEOUT_SECONDS = 120.0

INSTRUCTIONS: Mapping[PerturbationType, str] = {
    PerturbationType.DIRECTION: "reverse the direction of the effect the claim states "
    "(for example, increases becomes decreases, better becomes worse).",
    PerturbationType.CAUSAL: "turn the association or correlation the claim states into a "
    "causal statement (for example, is associated with becomes causes).",
    PerturbationType.OVERGENERALISATION: "widen the population, dataset or conditions the "
    "claim is about (for example, in mice becomes in mammals, on one dataset becomes in general).",
    PerturbationType.MISSING_COMPARATOR: "remove the comparator the claim names (for example, "
    "better than B becomes better), keeping the rest.",
}

EXPECTED: Mapping[PerturbationType, str] = {
    PerturbationType.DIRECTION: "is contradicted by it: the effect goes the other way.",
    PerturbationType.CAUSAL: "claims a causal link where the evidence reports an association.",
    PerturbationType.OVERGENERALISATION: "states more broadly than the evidence supports.",
    PerturbationType.MISSING_COMPARATOR: "leaves out the comparison the evidence makes.",
}


class CostCapReachedError(UtuxError):
    """A call could pass the cost cap, so it was not sent."""


def estimated_cost_usd(tokens_in: int, tokens_out: int, day: date) -> float:
    """The estimated cost of a call on `day` by the price table, an estimate only."""
    price = [p for p in PRICES if p.first_day <= day][-1]
    return (tokens_in * price.input_per_million + tokens_out * price.output_per_million) / 1e6


def cap_cost_usd(tokens_in: int, tokens_out: int) -> float:
    """The cost the cap counts: every token at the higher price."""
    return (
        tokens_in * CAP_PRICE.input_per_million + tokens_out * CAP_PRICE.output_per_million
    ) / 1e6


def load_prompt(version: str) -> str:
    """A versioned prompt of `utux/evalkit/prompts/`."""
    return files("utux.evalkit").joinpath(f"prompts/{version}.md").read_text(encoding="utf-8")


def gemini_provider(transport: Transport | None = None) -> OpenAICompatibleProvider:
    """Gemini's OpenAI-compatible endpoint; the key is read from `GEMINI_API_KEY` at each call."""
    return OpenAICompatibleProvider(
        name=PROVIDER_NAME,
        base_url=GEMINI_BASE_URL,
        api_key_env=GEMINI_KEY_VARIABLE,
        transport=transport,
    )


class CappedCaller:
    """Calls a provider under a cost cap and logs each call as one `model_call` event."""

    def __init__(
        self,
        log: EventLog,
        provider: ModelProvider,
        *,
        max_cost_usd: float,
        model: str = GEMINI_MODEL,
        today: Callable[[], date] = date.today,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Refuse any call that could take the capped spending past `max_cost_usd`."""
        if max_cost_usd <= 0:
            raise ValueError("the cost cap must be more than zero")
        self._log = log
        self._provider = provider
        self._cap = max_cost_usd
        self._model = model
        self._today = today
        self._clock = clock
        self.spent_cap_usd = 0.0
        self.estimated_usd = 0.0

    def _event(
        self,
        request: ModelRequest,
        status: EventStatus,
        prompt: str,
        *,
        reason: str | None = None,
        response: ModelResponse | None = None,
        started: float | None = None,
        estimate: float | None = None,
    ) -> None:
        usage = None if response is None else response.usage
        self._log.append(
            NewEvent(
                actor=ACTOR,
                type=EventType.MODEL_CALL,
                status=status,
                status_reason=reason,
                prompt_version=prompt,
                model=self._model if response is None else response.model,
                input_hash=input_hash(request),
                output_hash=None if response is None else output_hash(response),
                tokens_in=None if usage is None else usage.tokens_in,
                tokens_out=None if usage is None else usage.tokens_out,
                cost_usd=None if response is None else response.cost_usd,
                duration_ms=None if started is None else self._milliseconds(started),
                data={
                    "provider": self._provider.name,
                    "is_external": self._provider.is_external,
                    "estimated_cost_usd": estimate,
                },
            )
        )

    def call(self, messages: Sequence[Message], prompt_version: str) -> ModelResponse:
        """One call, logged.

        Raises:
            CostCapReachedError: The call could pass the cap; it is logged as
                refused with `budget_exhausted` and not sent.
            ModelProviderError: The call failed; it is logged with status
                `error`.
        """
        request = ModelRequest(
            model=self._model,
            messages=tuple(messages),
            timeout_seconds=TIMEOUT_SECONDS,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        )
        # A token is at least one byte, so the bytes bound the input tokens.
        bound_in = sum(len(m.content.encode("utf-8")) + 16 for m in messages)
        if self.spent_cap_usd + cap_cost_usd(bound_in, MAX_OUTPUT_TOKENS) > self._cap:
            self._event(request, EventStatus.REFUSED, prompt_version, reason=REFUSED_BUDGET)
            raise CostCapReachedError(
                f"the next call could pass the cap of {self._cap} USD "
                f"({self.spent_cap_usd:.4f} USD counted at the higher price)"
            )
        started = self._clock()
        try:
            response = self._provider.complete(request)
        except ModelProviderError as error:
            reason = status_reason(error)
            self._event(request, EventStatus.ERROR, prompt_version, reason=reason, started=started)
            raise
        usage = response.usage
        estimate = estimated_cost_usd(usage.tokens_in, usage.tokens_out, self._today())
        self.spent_cap_usd += cap_cost_usd(usage.tokens_in, usage.tokens_out)
        self.estimated_usd += estimate
        self._event(
            request,
            EventStatus.OK,
            prompt_version,
            response=response,
            started=started,
            estimate=estimate,
        )
        return response

    def _milliseconds(self, started: float) -> int:
        return max(0, round((self._clock() - started) * 1000))


def _json_answer(content: str) -> object:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{") :] if "{" in text else text
    try:
        return json.loads(text)
    except ValueError:
        return None


def _user(text: str) -> tuple[Message, ...]:
    return (Message(role=MessageRole.USER, content=text),)


def _perturb_one(
    parent: GoldItem, kind: PerturbationType, texts: Mapping[str, str], caller: CappedCaller
) -> GoldItem:
    original = parent.claims[0].text
    writer = load_prompt(WRITER_PROMPT).format(instruction=INSTRUCTIONS[kind], claim=original)
    answer = _json_answer(caller.call(_user(writer), WRITER_PROMPT).content)
    if isinstance(answer, dict) and answer.get("not_applicable") is True:
        raise Skip("not_applicable")
    claim = answer.get("claim") if isinstance(answer, dict) else None
    if not isinstance(claim, str) or not claim.strip() or "\n" in claim.strip():
        raise Skip("invalid_answer")
    claim = " ".join(claim.split())
    if claim.casefold() == " ".join(original.split()).casefold():
        raise Skip("unchanged")
    if len(claim) > 2 * len(original) + 40:
        raise Skip("invalid_answer")
    child = make_child(parent, kind, claim, None, Confirmation.MODEL_CHECK)
    evidence = "\n".join(
        evidence_text(pair, texts) for pair in parent.claims[0].pairs if pair.evidence_spans
    )
    check = load_prompt(CHECK_PROMPT).format(
        original=original,
        claim=claim,
        instruction=INSTRUCTIONS[kind],
        evidence=evidence or "(none)",
        expected=EXPECTED[kind],
    )
    verdict = _json_answer(caller.call(_user(check), CHECK_PROMPT).content)
    if not isinstance(verdict, dict) or not isinstance(verdict.get("disagree"), bool):
        raise Skip("invalid_answer")
    if verdict["disagree"]:
        raise Skip("flagged_by_check")
    return child


def build_model_perturbations(
    items: Sequence[GoldItem],
    texts: Mapping[str, str],
    caller: CappedCaller,
    *,
    seed: int,
    per_type: int,
    types: Sequence[PerturbationType] = MODEL_TYPES,
    parents: Iterable[str] | None = None,
    max_tries: int | None = None,
) -> PerturbationRun:
    """Up to `per_type` checked perturbations of each type, ML parents first.

    Parents are tried in a fixed order: ML items, then the others, each
    group shuffled by `seed`. A type stops after `per_type` successes or
    `max_tries` attempts. The run stops when the cap refuses a call.
    """
    allowed = None if parents is None else set(parents)
    candidates = sorted(
        (i for i in items if is_parent(i) and (allowed is None or i.item_id in allowed)),
        key=lambda i: i.item_id,
    )
    rng = random.Random(seed)
    ml = [i for i in candidates if i.domain is Domain.ML]
    others = [i for i in candidates if i.domain is not Domain.ML]
    rng.shuffle(ml)
    rng.shuffle(others)
    ordered = ml + others
    children: list[GoldItem] = []
    skipped: Counter[tuple[PerturbationType, str]] = Counter()
    for kind in types:
        made = 0
        for tries, parent in enumerate(ordered):
            if made >= per_type or (max_tries is not None and tries >= max_tries):
                break
            try:
                children.append(_perturb_one(parent, kind, texts, caller))
                made += 1
            except Skip as skip:
                skipped[(kind, skip.reason)] += 1
            except CostCapReachedError:
                return _run(children, skipped, stopped=True)
            except ModelAuthenticationError:
                # No call can succeed without a usable key: stop, do not count.
                raise
            except ModelProviderError:
                skipped[(kind, "call_failed")] += 1
    return _run(children, skipped, stopped=False)


def _run(
    children: list[GoldItem],
    skipped: Counter[tuple[PerturbationType, str]],
    *,
    stopped: bool,
) -> PerturbationRun:
    return PerturbationRun(
        tuple(sorted(children, key=lambda c: c.item_id)), dict(skipped), stopped_by_cap=stopped
    )
