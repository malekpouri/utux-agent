"""M0-13b: agreement between annotators.

Every expected value is worked out by hand in the comments, from small
invented examples or from the synthetic release listed in
`tests/fixtures/gold_release/README.md`. No label here is annotation.
"""

from pathlib import Path

import pytest
from utux.evalkit.agreement import (
    annotation_agreement,
    cohens_kappa,
    confusion_table,
    gwet_ac1,
    raw_agreement,
    span_overlap,
)

from utux.errors import GoldSetError
from utux.evalkit.gold import read_gold_release

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
