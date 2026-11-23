"""M0-15c: model-written perturbations with Gemini, on scripted and recorded answers only.

No test calls Gemini. The price table and the cap follow ADR-0019.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from provider_fakes import SYNTHETIC_KEY, ScriptedTransport, response
from synthetic_gold_corpus import synthetic_corpus
from utux.evalkit.model_perturb import (
    CHECK_PROMPT,
    GEMINI_BASE_URL,
    GEMINI_MODEL,
    WRITER_PROMPT,
    CappedCaller,
    build_model_perturbations,
    cap_cost_usd,
    estimated_cost_usd,
    gemini_provider,
    load_prompt,
)
from utux.evalkit.perturb import PerturbationType

from utux.errors import ContractValidationError, ModelProviderError
from utux.evalkit.gold import Confirmation, GoldItem, GoldStatus, PerturbationRecord
from utux.events.log import EventLog
from utux.interfaces.model_provider import Message, MessageRole
from utux.providers.scripted import ScriptedModelProvider, ScriptedReply
from utux.schemas.claim_ledger import ScopeFlag, SourceLabel
from utux.schemas.event import Event, EventStatus, EventType

TODAY = date(2026, 11, 23)


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[tuple[GoldItem, ...], dict[str, str]]:
    return synthetic_corpus(tmp_path / "data")


def _reply(content: object, tokens_in: int = 1000, tokens_out: int = 200) -> ScriptedReply:
    text = content if isinstance(content, str) else json.dumps(content)
    return ScriptedReply(content=text, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=None)


def _caller(tmp_path: Path, script: list[ScriptedReply], cap: float = 5.0) -> CappedCaller:
    provider = ScriptedModelProvider(script, name="gemini")
    return CappedCaller(
        EventLog(tmp_path / "events.jsonl"), provider, max_cost_usd=cap, today=lambda: TODAY
    )


def _events(tmp_path: Path) -> list[Event]:
    return list(EventLog(tmp_path / "events.jsonl"))


# The price table (ADR-0019) -------------------------------------------------------


def test_the_estimate_uses_the_price_of_the_day_and_the_cap_the_higher_price() -> None:
    assert estimated_cost_usd(1_000_000, 0, TODAY) == pytest.approx(0.75)
    assert estimated_cost_usd(0, 1_000_000, TODAY) == pytest.approx(3.75)
    assert estimated_cost_usd(0, 1_000_000, date(2026, 12, 31)) == pytest.approx(3.75)
    assert estimated_cost_usd(1_000_000, 1_000_000, date(2027, 1, 1)) == pytest.approx(9.0)
    # The cap prices every token at the higher price, whatever the day.
    assert cap_cost_usd(1_000_000, 1_000_000) == pytest.approx(9.0)


def test_the_prompts_are_versioned_files_in_the_package() -> None:
    assert (WRITER_PROMPT, CHECK_PROMPT) == ("perturb-writer@1", "perturb-check@1")
    assert "{claim}" in load_prompt(WRITER_PROMPT)
    assert "{evidence}" in load_prompt(CHECK_PROMPT)


# A run ---------------------------------------------------------------------------


def test_a_checked_perturbation_gets_model_check_and_its_constructed_label(
    tmp_path: Path, corpus: tuple[tuple[GoldItem, ...], dict[str, str]]
) -> None:
    items, texts = corpus
    caller = _caller(
        tmp_path,
        [
            _reply({"claim": "Alpha falls short of an accuracy of 81.0."}),
            _reply({"disagree": False}),
        ],
    )
    run = build_model_perturbations(
        items, texts, caller, seed=3, per_type=1, types=(PerturbationType.DIRECTION,)
    )
    (child,) = run.items
    # An ML parent is preferred over the biomedical ones.
    assert isinstance(child.hidden, PerturbationRecord)
    assert child.hidden.source_item == "G20000001"
    assert child.item_id == "G3520000001"
    assert child.hidden.confirmation is Confirmation.MODEL_CHECK
    assert child.hidden.confirmed_by is None
    assert child.hidden.target_error == "direction_mismatch"
    (claim,) = child.claims
    assert claim.text == "Alpha falls short of an accuracy of 81.0."
    assert claim.status is GoldStatus.CONTRADICTED
    (pair,) = claim.pairs
    assert (pair.agreement_label, pair.scope_flags) == (
        SourceLabel.CONTRADICTS,
        (ScopeFlag.DIRECTION_MISMATCH,),
    )


def test_every_call_is_a_model_call_event_with_an_estimated_cost_and_no_cost_usd(
    tmp_path: Path, corpus: tuple[tuple[GoldItem, ...], dict[str, str]]
) -> None:
    items, texts = corpus
    caller = _caller(
        tmp_path, [_reply({"claim": "Alpha has no accuracy of 81.0."}), _reply({"disagree": False})]
    )
    build_model_perturbations(
        items, texts, caller, seed=3, per_type=1, types=(PerturbationType.DIRECTION,)
    )
    events = _events(tmp_path)
    assert [e.type for e in events] == [EventType.MODEL_CALL, EventType.MODEL_CALL]
    assert [e.prompt_version for e in events] == [WRITER_PROMPT, CHECK_PROMPT]
    for event in events:
        assert event.status is EventStatus.OK
        assert event.cost_usd is None
        # 1000 tokens in at 0.75 and 200 out at 3.75 per million.
        assert event.data["estimated_cost_usd"] == pytest.approx(0.0015)
    assert caller.estimated_usd == pytest.approx(0.003)
    # Counted at the higher price for the cap: 1000 at 1.50 and 200 at 7.50.
    assert caller.spent_cap_usd == pytest.approx(0.006)


@pytest.mark.parametrize(
    ("writer", "checker", "reason"),
    [
        ({"claim": "Alpha has no accuracy of 81.0."}, {"disagree": True}, "flagged_by_check"),
        ({"not_applicable": True}, None, "not_applicable"),
        ("not json", None, "invalid_answer"),
        ({"claim": "Alpha reaches an accuracy of 81.0."}, None, "unchanged"),
        ({"claim": "Alpha has no accuracy of 81.0."}, "not json", "invalid_answer"),
    ],
)
def test_items_without_a_clean_check_are_dropped_and_counted(
    tmp_path: Path,
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
    writer: object,
    checker: object,
    reason: str,
) -> None:
    items, texts = corpus
    script = [_reply(writer)] + ([_reply(checker)] if checker is not None else [])
    caller = _caller(tmp_path, script)
    run = build_model_perturbations(
        items, texts, caller, seed=3, per_type=1, types=(PerturbationType.DIRECTION,), max_tries=1
    )
    assert run.items == ()
    assert run.skipped[(PerturbationType.DIRECTION, reason)] == 1


def test_the_cap_refuses_a_call_that_could_pass_it_and_stops_the_run(
    tmp_path: Path, corpus: tuple[tuple[GoldItem, ...], dict[str, str]]
) -> None:
    items, texts = corpus
    provider = ScriptedModelProvider(
        [_reply({"claim": "Alpha has no accuracy of 81.0."}, 5000, 1500)], name="gemini"
    )
    caller = CappedCaller(
        EventLog(tmp_path / "events.jsonl"), provider, max_cost_usd=0.02, today=lambda: TODAY
    )
    run = build_model_perturbations(
        items, texts, caller, seed=3, per_type=1, types=(PerturbationType.DIRECTION,)
    )
    assert run.stopped_by_cap is True
    assert len(provider.requests) == 1
    events = _events(tmp_path)
    assert [(e.status, e.status_reason) for e in events] == [
        (EventStatus.OK, None),
        (EventStatus.REFUSED, "budget_exhausted"),
    ]
    assert caller.spent_cap_usd <= 0.02


def test_a_cap_too_small_for_one_call_sends_nothing(
    tmp_path: Path, corpus: tuple[tuple[GoldItem, ...], dict[str, str]]
) -> None:
    items, texts = corpus
    provider = ScriptedModelProvider([], name="gemini")
    caller = CappedCaller(
        EventLog(tmp_path / "events.jsonl"), provider, max_cost_usd=0.001, today=lambda: TODAY
    )
    run = build_model_perturbations(items, texts, caller, seed=3, per_type=1)
    assert (run.items, run.stopped_by_cap, provider.requests) == ((), True, [])


# Gemini through the OpenAI-compatible client, on a recorded answer -------------------


def test_gemini_is_reached_with_the_key_from_gemini_api_key_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", SYNTHETIC_KEY)
    transport = ScriptedTransport(response(200, "gemini_completion.json"))
    caller = CappedCaller(
        EventLog(tmp_path / "events.jsonl"),
        gemini_provider(transport=transport),
        max_cost_usd=1.0,
        today=lambda: TODAY,
    )
    answer = caller.call((Message(role=MessageRole.USER, content="Synthetic."),), CHECK_PROMPT)
    assert answer.content == '{"disagree": false}'
    ((request, _),) = transport.calls
    assert request.url == GEMINI_BASE_URL + "/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {SYNTHETIC_KEY}"
    assert json.loads(request.body)["model"] == GEMINI_MODEL == "gemini-3.8-flash"
    (event,) = _events(tmp_path)
    assert (event.tokens_in, event.tokens_out, event.cost_usd) == (812, 37, None)
    assert event.data["provider"] == "gemini"
    assert SYNTHETIC_KEY not in (tmp_path / "events.jsonl").read_text()


def test_without_the_key_nothing_is_sent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    transport = ScriptedTransport(response(200, "gemini_completion.json"))
    caller = CappedCaller(
        EventLog(tmp_path / "events.jsonl"),
        gemini_provider(transport=transport),
        max_cost_usd=1.0,
        today=lambda: TODAY,
    )
    with pytest.raises(ModelProviderError):
        caller.call((Message(role=MessageRole.USER, content="Synthetic."),), CHECK_PROMPT)
    assert transport.calls == []


# The event key (ADR-0019) ---------------------------------------------------------


def test_estimated_cost_usd_is_a_number_of_zero_or_more_or_null(tmp_path: Path) -> None:
    caller = _caller(tmp_path, [_reply("x")])
    caller.call((Message(role=MessageRole.USER, content="Synthetic."),), WRITER_PROMPT)
    document = json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0])
    for valid in (0.0, None):
        Event.validate_document(
            {**document, "data": {**document["data"], "estimated_cost_usd": valid}}, "s"
        )
    legacy = {key: value for key, value in document["data"].items() if key != "estimated_cost_usd"}
    Event.validate_document({**document, "data": legacy}, "s")
    with pytest.raises(ContractValidationError):
        Event.validate_document(
            {**document, "data": {**document["data"], "estimated_cost_usd": -1.0}}, "s"
        )
