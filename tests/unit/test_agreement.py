"""M0-13b: agreement between annotators.

Every expected value is worked out by hand in the comments, from small
invented examples or from the synthetic release listed in
`tests/fixtures/gold_release/README.md`. No label here is annotation.
"""

from pathlib import Path

import pytest

from utux.errors import GoldSetError
from utux.evalkit.agreement import (
    annotation_agreement,
    cohens_kappa,
    confusion_table,
    gwet_ac1,
    match_claims,
    raw_agreement,
    span_overlap,
)
from utux.evalkit.gold import EvidenceSpan, read_gold_release

RELEASE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "gold_release" / "synthetic_release.jsonl"
)

# Ten invented yes/no judgements: both yes 4, both no 3, first yes and
# second no 2, first no and second yes 1.
PAIRS = [("yes", "yes")] * 4 + [("no", "no")] * 3 + [("yes", "no")] * 2 + [("no", "yes")]
LABELS = ("yes", "no")


def test_raw_agreement() -> None:
    # 7 of 10 agree.
    assert raw_agreement(PAIRS) == pytest.approx(0.7)


def test_confusion_table_rows_are_the_first_annotator() -> None:
    assert confusion_table(PAIRS, LABELS) == {
        "yes": {"yes": 4, "no": 2},
        "no": {"yes": 1, "no": 3},
    }


def test_cohens_kappa() -> None:
    # p_o = 0.7; first yes 0.6, second yes 0.5;
    # p_e = 0.6 * 0.5 + 0.4 * 0.5 = 0.5; kappa = 0.2 / 0.5 = 0.4.
    assert cohens_kappa(PAIRS, LABELS) == pytest.approx(0.4)


def test_gwet_ac1() -> None:
    # pi_yes = (0.6 + 0.5) / 2 = 0.55, pi_no = 0.45, Q = 2;
    # p_e = (0.55 * 0.45 + 0.45 * 0.55) / 1 = 0.495;
    # AC1 = (0.7 - 0.495) / (1 - 0.495) = 0.205 / 0.505 = 41/101.
    assert gwet_ac1(PAIRS, LABELS) == pytest.approx(41 / 101)


def test_kappa_is_undefined_when_both_always_give_one_label() -> None:
    # p_e = 1, so kappa has no value; AC1 is 1 (p_e = 0 with pi = 1).
    pairs = [("yes", "yes")] * 5
    assert cohens_kappa(pairs, LABELS) is None
    assert gwet_ac1(pairs, LABELS) == pytest.approx(1.0)


def test_agreement_needs_pairs_and_known_labels() -> None:
    with pytest.raises(GoldSetError):
        raw_agreement([])
    with pytest.raises(GoldSetError, match="maybe"):
        cohens_kappa([("yes", "maybe")], LABELS)


def test_span_overlap_is_counted_in_tokens() -> None:
    # Tokens: a [0, 1), b [2, 3), c [4, 5), d [6, 7), e [8, 9).
    # First annotator (0, 5): a, b, c. Second (4, 9): c, d, e.
    # Shared: c. F1 = 2 * 1 / (3 + 3) = 1/3. IoU = 1 / 5.
    overlap = span_overlap([(0, 5)], [(4, 9)], "a b c d e")
    assert overlap.f1 == pytest.approx(1 / 3)
    assert overlap.iou == pytest.approx(1 / 5)


def test_span_overlap_counts_a_token_touched_by_a_span() -> None:
    # (1, 3) touches b only; the space at 1 is no token.
    overlap = span_overlap([(1, 3)], [(2, 3)], "a b c")
    assert (overlap.f1, overlap.iou) == (1.0, 1.0)


def test_span_overlap_of_two_empty_selections_is_undefined() -> None:
    overlap = span_overlap([], [], "a b c")
    assert (overlap.f1, overlap.iou) == (None, None)


def test_span_overlap_of_one_empty_selection_is_zero() -> None:
    overlap = span_overlap([(0, 1)], [], "a b c")
    assert (overlap.f1, overlap.iou) == (0.0, 0.0)


# A release


def test_status_agreement_on_the_synthetic_release() -> None:
    report = annotation_agreement(read_gold_release(RELEASE))
    status = report.status
    # 10 claims; the annotators differ on G9001 (partially_supported against
    # verified) and G9006 (contradicted against verified): p_o = 8/10.
    assert status.units == 10
    assert status.raw_agreement == pytest.approx(0.8)
    # First annotator: verified 5, partially 2, contradicted 2, insufficient 1.
    # Second: verified 7, partially 1, contradicted 1, insufficient 1.
    # p_e = (5*7 + 2*1 + 2*1 + 1*1) / 100 = 0.4; kappa = 0.4 / 0.6 = 2/3.
    assert status.cohens_kappa == pytest.approx(2 / 3)
    # pi: verified 0.6, partially 0.15, contradicted 0.15, insufficient 0.1.
    # sum pi(1 - pi) = 0.24 + 0.1275 + 0.1275 + 0.09 = 0.585; / 3 = 0.195.
    # AC1 = (0.8 - 0.195) / 0.805 = 121/161.
    assert status.gwet_ac1 == pytest.approx(121 / 161)
    assert status.confusion == {
        "verified": {
            "verified": 5,
            "partially_supported": 0,
            "contradicted": 0,
            "insufficient_evidence": 0,
        },
        "partially_supported": {
            "verified": 1,
            "partially_supported": 1,
            "contradicted": 0,
            "insufficient_evidence": 0,
        },
        "contradicted": {
            "verified": 1,
            "partially_supported": 0,
            "contradicted": 1,
            "insufficient_evidence": 0,
        },
        "insufficient_evidence": {
            "verified": 0,
            "partially_supported": 0,
            "contradicted": 0,
            "insufficient_evidence": 1,
        },
    }


def test_pair_label_and_flag_agreement_on_the_synthetic_release() -> None:
    report = annotation_agreement(read_gold_release(RELEASE))
    # 11 pairs; the second annotator gave entails on G9001 and G9006.
    assert report.agreement_label.units == 11
    assert report.agreement_label.raw_agreement == pytest.approx(9 / 11)
    direction = report.scope_flags["direction_mismatch"]
    # First annotator yes on G9003-c1-s1, G9003-c1-s2 and G9006; second only
    # on the two G9003 pairs. p_o = 10/11.
    assert direction.raw_agreement == pytest.approx(10 / 11)
    # p_e = (3/11)(2/11) + (8/11)(9/11) = 78/121;
    # kappa = (110/121 - 78/121) / (43/121) = 32/43.
    assert direction.cohens_kappa == pytest.approx(32 / 43)
    # No pair has certainty_escalation from either annotator.
    assert report.scope_flags["certainty_escalation"].raw_agreement == pytest.approx(1.0)
    assert report.scope_flags["certainty_escalation"].cohens_kappa is None


def test_agreement_report_holds_no_item_or_claim_id() -> None:
    text = str(annotation_agreement(read_gold_release(RELEASE)).to_json())
    assert "G90" not in text


# Claim extraction, review flag and spans at release level

SOURCE_TEXT = "synthetic fixture content\n"  # the text whose SHA-256 the fixtures hold


def _sources() -> dict[str, str]:
    return {
        pair.source_id: SOURCE_TEXT
        for item in read_gold_release(RELEASE)
        for claim in item.claims
        for pair in claim.pairs
    }


def test_claim_lists_match_by_half_of_the_longer_span() -> None:
    # (0, 10) and (5, 15) share 5 of 10 characters: a match.
    assert match_claims([(0, 10)], [(5, 15)]) == 1
    # (0, 10) and (6, 16) share 4 of 10: no match.
    assert match_claims([(0, 10)], [(6, 16)]) == 0
    # (0, 4) and (0, 10) share 4 of the longer 10: no match.
    assert match_claims([(0, 4)], [(0, 10)]) == 0
    # One to one: two spans on the first side cannot both match one span.
    assert match_claims([(0, 10), (0, 10)], [(0, 10)]) == 1


def test_claim_extraction_agreement_on_the_synthetic_release() -> None:
    extraction = annotation_agreement(read_gold_release(RELEASE)).claim_extraction
    # Each annotator lists the one claim of every item; the second annotator
    # also lists (0, 18) in G9001 and G9006, which matches nothing.
    # First 10 claims, second 12, matched 10: share 2 * 10 / 22 = 10/11.
    assert (extraction.first, extraction.second, extraction.matched) == (10, 12, 10)
    assert extraction.share == pytest.approx(10 / 11)


def test_review_flag_agreement_on_the_synthetic_release() -> None:
    review = annotation_agreement(read_gold_release(RELEASE)).expert_would_review
    # Both annotators said no for all 10 claims.
    assert review.units == 10
    assert review.raw_agreement == pytest.approx(1.0)
    assert review.cohens_kappa is None


def test_span_agreement_needs_source_texts() -> None:
    assert annotation_agreement(read_gold_release(RELEASE)).evidence_spans is None


def test_span_agreement_at_release_level() -> None:
    items = read_gold_release(RELEASE)
    # Every pair: both annotators chose (10, 60): "fixture" and "content".
    spans = annotation_agreement(items, _sources()).evidence_spans
    assert spans is not None
    assert spans.pairs == 11
    assert spans.mean_f1 == pytest.approx(1.0)
    assert spans.mean_iou == pytest.approx(1.0)


def test_span_agreement_with_one_disagreeing_pair() -> None:
    items = list(read_gold_release(RELEASE))
    g9001 = items[1]
    claim = g9001.claims[0]
    pair = claim.pairs[0]
    raw = dict(pair.raw)
    # The second annotator now chose (0, 9): "synthetic" only. Shared: none.
    raw["a92"] = raw["a92"].model_copy(
        update={"evidence_spans": (EvidenceSpan(passage_id="p001", offsets=(0, 9)),)}
    )
    changed = claim.model_copy(update={"pairs": (pair.model_copy(update={"raw": raw}),)})
    items[1] = g9001.model_copy(update={"claims": (changed,)})
    spans = annotation_agreement(items, _sources()).evidence_spans
    assert spans is not None
    # Ten pairs with F1 and IoU 1, one with 0: means 10/11.
    assert spans.mean_f1 == pytest.approx(10 / 11)
    assert spans.mean_iou == pytest.approx(10 / 11)


def test_a_source_text_that_does_not_match_its_hash_is_refused() -> None:
    sources = _sources()
    sources["synthetic:sg-synthetic-a-paper"] = "another text\n"
    with pytest.raises(GoldSetError, match="synthetic:sg-synthetic-a-paper"):
        annotation_agreement(read_gold_release(RELEASE), sources)


def test_a_missing_source_text_is_refused() -> None:
    sources = _sources()
    del sources["synthetic:sg-synthetic-h-paper"]
    with pytest.raises(GoldSetError, match="synthetic:sg-synthetic-h-paper"):
        annotation_agreement(read_gold_release(RELEASE), sources)
