"""M0-13b: metrics on their stated units (RFC-002, section 7).

The reference labels are those of the synthetic release listed in
`tests/fixtures/gold_release/README.md`; the system output is invented here.
Every expected value is worked out by hand in the comments.
"""

import json
from pathlib import Path

import pytest
from utux.evalkit.metrics import (
    ClaimPrediction,
    PairPrediction,
    Predictions,
    evaluate,
    label_scores,
    metrics_only,
)

from utux.errors import GoldSetError
from utux.evalkit.gold import GoldItem, read_gold_release
from utux.schemas.claim_ledger import ClaimStatus, ScopeFlag, SourceLabel

RELEASE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "gold_release" / "synthetic_release.jsonl"
)

V = ClaimStatus.VERIFIED
P = ClaimStatus.PARTIALLY_SUPPORTED
C = ClaimStatus.CONTRADICTED
I = ClaimStatus.INSUFFICIENT_EVIDENCE  # noqa: E741
U = ClaimStatus.UNVERIFIED

# Reference status: G9000 V, G9001 P, G9002 V, G9003 C, G9004 I, G9005 V,
# G9006 C, G9007 V, G9008 P, G9009 V.
CLAIMS = {
    "G9000-c1": ClaimPrediction(V, sent_to_review=False),
    "G9001-c1": ClaimPrediction(V, sent_to_review=True),  # wrong: reference P
    "G9002-c1": ClaimPrediction(V, sent_to_review=False),
    "G9003-c1": ClaimPrediction(V, sent_to_review=True),  # wrong: reference C
    "G9004-c1": ClaimPrediction(I, sent_to_review=False),
    "G9005-c1": ClaimPrediction(U, sent_to_review=False, failure_reason="model_timeout"),
    "G9006-c1": ClaimPrediction(C, sent_to_review=False),
    "G9007-c1": ClaimPrediction(P, sent_to_review=True),  # wrong: reference V
    "G9008-c1": ClaimPrediction(P, sent_to_review=False),
    "G9009-c1": ClaimPrediction(V, sent_to_review=False),
}

E, PA, N, CO = (
    SourceLabel.ENTAILS,
    SourceLabel.PARTIAL,
    SourceLabel.NEUTRAL,
    SourceLabel.CONTRADICTS,
)
DIR, MAG, OVER, MET, CAUS = (
    ScopeFlag.DIRECTION_MISMATCH,
    ScopeFlag.MAGNITUDE_MISMATCH,
    ScopeFlag.OVERGENERALISATION,
    ScopeFlag.METRIC_MISMATCH,
    ScopeFlag.CAUSAL_OVERREACH,
)
# Reference pairs: G9000 E; G9001 PA {OVER}; G9002 E; G9003-c1-s1 CO {DIR};
# G9003-c1-s2 CO {DIR, MAG}; G9004 N; G9005 E; G9006 CO {DIR}; G9007 E;
# G9008 PA {MET}; G9009 E.
PAIRS = {
    "G9000-c1-s1": PairPrediction(E),
    "G9001-c1-s1": PairPrediction(PA, frozenset({OVER})),
    "G9002-c1-s1": PairPrediction(E),
    "G9003-c1-s1": PairPrediction(CO, frozenset({DIR})),
    "G9003-c1-s2": PairPrediction(E, frozenset({DIR})),  # wrong label, misses MAG
    "G9004-c1-s1": PairPrediction(None),  # not assessed
    "G9005-c1-s1": PairPrediction(E),
    "G9006-c1-s1": PairPrediction(CO),  # misses DIR
    "G9007-c1-s1": PairPrediction(E),
    "G9008-c1-s1": PairPrediction(PA, frozenset({MET, CAUS})),  # extra CAUS
    "G9009-c1-s1": PairPrediction(E),
}


def _items() -> list[GoldItem]:
    return list(read_gold_release(RELEASE))


def _predictions() -> Predictions:
    return Predictions(claims=CLAIMS, pairs=PAIRS)


def _with_ambiguous(items: list[GoldItem], claim_id: str) -> list[GoldItem]:
    result = []
    for item in items:
        claims = tuple(
            claim.model_copy(update={"ambiguous": True}) if claim.claim_id == claim_id else claim
            for claim in item.claims
        )
        result.append(item.model_copy(update={"claims": claims}))
    return result


# Generic label scores


def test_label_scores_on_a_small_example() -> None:
    # Reference a a b b c; predicted a b b b -, with - meaning no answer.
    scores = label_scores(["a", "a", "b", "b", "c"], ["a", "b", "b", "b", None], ("a", "b", "c"))
    a, b, c = scores.per_label["a"], scores.per_label["b"], scores.per_label["c"]
    # a: TP 1, FP 0, FN 1. b: TP 2, FP 1, FN 0. c: TP 0, FP 0, FN 1.
    assert (a.tp, a.fp, a.fn) == (1, 0, 1)
    assert (b.tp, b.fp, b.fn) == (2, 1, 0)
    assert (c.tp, c.fp, c.fn) == (0, 0, 1)
    assert a.precision == pytest.approx(1.0)
    assert a.recall == pytest.approx(0.5)
    assert a.f1 == pytest.approx(2 / 3)
    assert b.precision == pytest.approx(2 / 3)
    assert b.f1 == pytest.approx(0.8)
    # No prediction of c: precision undefined, recall 0, F1 0.
    assert c.precision is None
    assert c.recall == pytest.approx(0.0)
    assert c.f1 == pytest.approx(0.0)
    # False-positive rate of b: FP 1 over the 3 items whose reference is not b.
    assert b.false_positive_rate == pytest.approx(1 / 3)
    # Macro-F1 = (2/3 + 0.8 + 0) / 3 = 22/45.
    assert scores.macro_f1 == pytest.approx(22 / 45)


def test_a_label_absent_from_both_sides_has_no_f1_and_is_left_out_of_macro_f1() -> None:
    scores = label_scores(["a", "b"], ["a", "b"], ("a", "b", "c"))
    assert scores.per_label["c"].f1 is None
    assert scores.macro_f1 == pytest.approx(1.0)


# Claims (S6 and the headline metrics)


def test_status_scores_per_claim() -> None:
    claims = evaluate(_items(), _predictions()).claims
    # G9003 has two pairs but is one claim.
    assert claims.claims == 10
    status = claims.status.per_label
    # verified: TP G9000 G9002 G9009 = 3; FP G9001 G9003 = 2; FN G9005 G9007 = 2.
    assert (status["verified"].tp, status["verified"].fp, status["verified"].fn) == (3, 2, 2)
    assert status["verified"].f1 == pytest.approx(3 / 5)
    # partially_supported: TP G9008, FP G9007, FN G9001: F1 1/2.
    assert status["partially_supported"].f1 == pytest.approx(1 / 2)
    # contradicted: TP G9006, FN G9003: precision 1, recall 1/2, F1 2/3.
    assert status["contradicted"].f1 == pytest.approx(2 / 3)
    assert status["insufficient_evidence"].f1 == pytest.approx(1.0)
    # (3/5 + 1/2 + 2/3 + 1) / 4 = 83/120.
    assert claims.status.macro_f1 == pytest.approx(83 / 120)
    # False-positive rate of verified: 2 over the 5 claims not verified.
    assert status["verified"].false_positive_rate == pytest.approx(2 / 5)


def test_headline_metrics() -> None:
    claims = evaluate(_items(), _predictions()).claims
    # Marked verified: 5, of which G9001 and G9003 are not verified.
    assert (claims.false_verified_rate.numerator, claims.false_verified_rate.denominator) == (2, 5)
    assert claims.false_verified_rate.value == pytest.approx(0.4)
    # Reference contradicted: G9003, G9006; G9003 marked verified.
    assert (claims.critical_miss_rate.numerator, claims.critical_miss_rate.denominator) == (1, 2)
    # Reference verified: 5; marked verified: G9000 G9002 G9009.
    assert claims.verified_coverage.value == pytest.approx(3 / 5)
    # Sent to review: G9001 G9003 G9007, of 10.
    assert claims.review_load.value == pytest.approx(3 / 10)
    # Left unverified: G9005, of 10.
    assert claims.failure_rate.value == pytest.approx(1 / 10)
    assert claims.failure_reasons == {"model_timeout": 1}
    # Wrong statuses (unverified is not wrong): G9001 G9003 G9007, all sent to review.
    assert (claims.wrong_status_flagged.numerator, claims.wrong_status_flagged.denominator) == (
        3,
        3,
    )


def test_an_unverified_claim_counts_against_verified_coverage() -> None:
    claims = evaluate(_items(), _predictions()).claims
    # G9005 is reference verified and left unverified: it is a false negative.
    assert claims.status.per_label["verified"].fn == 2


# Pairs (S3, S5 and S4)


def test_agreement_label_scores_per_pair() -> None:
    pairs = evaluate(_items(), _predictions()).pairs
    assert pairs.pairs == 11
    labels = pairs.agreement_label.per_label
    # entails: TP 5, FP G9003-c1-s2: F1 = 10/11.
    assert labels["entails"].f1 == pytest.approx(10 / 11)
    assert labels["partial"].f1 == pytest.approx(1.0)
    # contradicts: TP 2, FN G9003-c1-s2: F1 = 4/5.
    assert labels["contradicts"].f1 == pytest.approx(4 / 5)
    # neutral: G9004 not assessed: TP 0, FN 1: F1 0.
    assert labels["neutral"].f1 == pytest.approx(0.0)
    assert labels["conflicting"].f1 is None
    # (10/11 + 1 + 4/5 + 0) / 4 = 149/220.
    assert pairs.agreement_label.macro_f1 == pytest.approx(149 / 220)


def test_scope_flags_are_scored_per_flag_with_micro_and_macro_averages() -> None:
    flags = evaluate(_items(), _predictions()).pairs.scope_flags
    per = flags.per_label
    # direction_mismatch: TP 2 (G9003 s1, s2), FN 1 (G9006): F1 4/5.
    assert (per["direction_mismatch"].tp, per["direction_mismatch"].fn) == (2, 1)
    assert per["direction_mismatch"].f1 == pytest.approx(4 / 5)
    assert per["magnitude_mismatch"].f1 == pytest.approx(0.0)
    assert per["overgeneralisation"].f1 == pytest.approx(1.0)
    assert per["metric_mismatch"].f1 == pytest.approx(1.0)
    # causal_overreach: FP 1, no reference: precision 0, recall undefined, F1 0.
    assert per["causal_overreach"].precision == pytest.approx(0.0)
    assert per["causal_overreach"].recall is None
    assert per["causal_overreach"].f1 == pytest.approx(0.0)
    assert per["certainty_escalation"].f1 is None
    # Micro: TP 4, FP 1, FN 2: precision 4/5, recall 2/3, F1 8/11.
    assert flags.micro is not None
    assert flags.micro.f1 == pytest.approx(8 / 11)
    # Macro over the five defined F1: (4/5 + 0 + 1 + 1 + 0) / 5 = 14/25.
    assert flags.macro_f1 == pytest.approx(14 / 25)


# Ambiguous claims


def test_ambiguous_claims_are_excluded_and_reported_separately() -> None:
    items = _with_ambiguous(_items(), "G9004-c1")
    result = evaluate(items, _predictions())
    assert result.claims.claims == 9
    assert result.pairs.pairs == 10
    # insufficient_evidence no longer occurs on either side.
    assert result.claims.status.per_label["insufficient_evidence"].f1 is None
    # (3/5 + 1/2 + 2/3) / 3 = 53/90.
    assert result.claims.status.macro_f1 == pytest.approx(53 / 90)
    # neutral no longer occurs: (10/11 + 1 + 4/5) / 3 = 149/165.
    assert result.pairs.agreement_label.macro_f1 == pytest.approx(149 / 165)
    assert result.ambiguous_claims.claims == 1
    assert result.ambiguous_pairs.pairs == 1
    assert result.ambiguous_claims.status.per_label["insufficient_evidence"].tp == 1


# Inputs


def test_a_missing_prediction_is_an_error() -> None:
    claims = dict(CLAIMS)
    del claims["G9007-c1"]
    with pytest.raises(GoldSetError, match="G9007-c1"):
        evaluate(_items(), Predictions(claims=claims, pairs=PAIRS))


def test_an_unverified_prediction_needs_a_failure_reason() -> None:
    with pytest.raises(GoldSetError, match="failure reason"):
        ClaimPrediction(U, sent_to_review=False)


# Metrics only


def test_metrics_only_returns_numbers_and_no_labels_of_items() -> None:
    report = metrics_only(_items(), _predictions())
    text = json.dumps(report)
    assert "G90" not in text
    assert "synthetic" not in text.lower()
    assert report["claims"]["false_verified_rate"] == {
        "numerator": 2,
        "denominator": 5,
        "value": 0.4,
    }


def test_metrics_only_prints_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    metrics_only(_items(), _predictions())
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
