"""M0-15c: perturbations built by fixed rules, with no model, on a synthetic corpus.

The labels follow from each construction (gold v0 strategy, section 6): the
parent's pair labels are kept except where the type names one, the type's
flag is added, and the status is the guideline's (`guideline_status`).
"""

import re
from pathlib import Path

import pytest
from synthetic_gold_corpus import item, synthetic_corpus
from utux.evalkit.perturb import (
    HEDGES,
    METRIC_GROUPS,
    PerturbationType,
    build_rule_perturbations,
)

from utux.evalkit.gold import (
    Confirmation,
    GoldItem,
    GoldStatus,
    NotScored,
    Origin,
    PerturbationRecord,
    check_release,
)
from utux.schemas.claim_ledger import ScopeFlag, SourceLabel


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[tuple[GoldItem, ...], dict[str, str]]:
    return synthetic_corpus(tmp_path)


def _children(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]], kind: PerturbationType
) -> list[GoldItem]:
    items, texts = corpus
    run = build_rule_perturbations(items, texts, seed=7)
    return [i for i in run.items if PerturbationType.of(i) is kind]


def _record(child: GoldItem) -> PerturbationRecord:
    assert isinstance(child.hidden, PerturbationRecord)
    return child.hidden


def test_the_lists_are_fixed_and_documented() -> None:
    assert "potentially" in HEDGES
    assert "perhaps" in HEDGES
    assert METRIC_GROUPS["ml"][:2] == ("accuracy", "precision")
    assert all(word == word.lower() for word in HEDGES)


def test_a_number_change_contradicts_with_a_number_found_nowhere_in_the_source(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = corpus
    (child,) = [
        c
        for c in _children(corpus, PerturbationType.NUMBER_CHANGE)
        if c.item_id.endswith("10000001")
    ]
    assert child.item_id == "G3210000001"
    assert child.origin is Origin.PERTURBED
    (claim,) = child.claims
    assert claim.text == "Drug A potentially lowered blood pressure by 24 percent in mice."
    assert claim.status is GoldStatus.CONTRADICTED
    (pair,) = claim.pairs
    assert pair.agreement_label is SourceLabel.CONTRADICTS
    assert pair.scope_flags == (ScopeFlag.MAGNITUDE_MISMATCH,)
    parent = item(items, "G10000001")
    assert pair.evidence_spans == parent.claims[0].pairs[0].evidence_spans
    assert not re.search(r"(?<![\d.])24(?![\d.])", texts[pair.text_hash])
    record = _record(child)
    assert (record.target_error, record.confirmation, record.confirmed_by) == (
        "magnitude_mismatch",
        Confirmation.DETERMINISTIC,
        None,
    )
    assert record.source_item == "G10000001"


def test_a_child_carries_its_parents_licence_and_redistribution_limit(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, _ = corpus
    for child in _children(corpus, PerturbationType.NUMBER_CHANGE):
        parent = item(items, _record(child).source_item)
        assert child.provenance is not None
        assert parent.provenance is not None
        assert child.provenance.licence == parent.provenance.licence
        assert child.provenance.text_redistributable is parent.provenance.text_redistributable
        assert child.domain is parent.domain
        # A flagged child is scored on S4; the parent's other exclusions stay.
        assert NotScored.S4 not in child.provenance.not_scored


def test_hedge_removal_flags_certainty_escalation_and_keeps_the_guidelines_status(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    (child,) = _children(corpus, PerturbationType.HEDGE_REMOVAL)
    (claim,) = child.claims
    assert claim.text == "Drug A lowered blood pressure by 12 percent in mice."
    (pair,) = claim.pairs
    assert pair.agreement_label is SourceLabel.ENTAILS
    assert pair.scope_flags == (ScopeFlag.CERTAINTY_ESCALATION,)
    # A minor flag leaves an entailed claim verified (guideline, section 5.4).
    assert claim.status is GoldStatus.VERIFIED
    assert _record(child).target_error == "certainty_escalation"


def test_a_metric_swap_uses_a_metric_absent_from_the_source(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    _, texts = corpus
    (child,) = _children(corpus, PerturbationType.METRIC_SWAP)
    (claim,) = child.claims
    assert claim.text == "Alpha reaches a precision of 81.0."
    (pair,) = claim.pairs
    assert pair.scope_flags == (ScopeFlag.METRIC_MISMATCH,)
    assert "precision" not in texts[pair.text_hash].lower()
    # A major flag on an entailed claim: partially supported.
    assert claim.status is GoldStatus.PARTIALLY_SUPPORTED
    assert child.provenance is not None
    assert child.provenance.not_scored == (NotScored.S2,)


def test_the_uncited_abstract_is_the_most_similar_one_the_claim_does_not_cite(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    children = _children(corpus, PerturbationType.UNCITED_ABSTRACT)
    child = next(c for c in children if _record(c).source_item == "G10000001")
    (claim,) = child.claims
    assert claim.text == "Drug A potentially lowered blood pressure by 12 percent in mice."
    (pair,) = claim.pairs
    assert pair.source_id == "scifact-doc-104"
    assert pair.source_group == "scifact-doc-104"
    assert pair.agreement_label is SourceLabel.NEUTRAL
    assert pair.evidence_spans == ()
    assert claim.status is GoldStatus.INSUFFICIENT_EVIDENCE
    assert child.provenance is not None
    assert child.provenance.not_scored == (NotScored.S4,)
    # SciFact parents only.
    assert all(c.provenance and c.provenance.dataset == "scifact" for c in children)


def test_uncited_abstracts_are_capped(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = corpus
    run = build_rule_perturbations(items, texts, seed=7, max_uncited=0)
    assert not [i for i in run.items if PerturbationType.of(i) is PerturbationType.UNCITED_ABSTRACT]
    assert run.skipped[(PerturbationType.UNCITED_ABSTRACT, "cap_reached")] >= 1


def test_only_verified_parents_are_perturbed_and_skips_are_counted(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = corpus
    run = build_rule_perturbations(items, texts, seed=7)
    parents = {_record(child).source_item for child in run.items}
    assert all(item(items, p).claims[0].status is GoldStatus.VERIFIED for p in parents)
    assert run.skipped[(PerturbationType.HEDGE_REMOVAL, "no_hedge")] >= 1
    assert run.skipped[(PerturbationType.NUMBER_CHANGE, "no_number_in_evidence")] >= 1
    assert run.skipped[(PerturbationType.METRIC_SWAP, "no_metric")] >= 1


def test_the_build_is_deterministic_and_every_child_fits_the_release_rules(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = corpus
    first = build_rule_perturbations(items, texts, seed=7)
    assert first == build_rule_perturbations(items, texts, seed=7)
    problems = check_release([*items, *first.items]).problems
    assert {p.code for p in problems} <= {"split_not_set"}
    assert all(c.claims[0].pairs[0].text_hash in texts for c in first.items)
    summary = first.summary()
    assert summary["items"] == len(first.items)
    assert set(summary["by_type"]) <= {kind.value for kind in PerturbationType}
