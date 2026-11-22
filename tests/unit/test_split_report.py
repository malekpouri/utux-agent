"""M0-13a: the split report.

The release is synthetic; its items and their labels are listed, by hand, in
`tests/fixtures/gold_release/README.md`. Every count below is taken from that
table.
"""

from pathlib import Path

import pytest

from utux.errors import GoldSetError
from utux.evalkit.gold import read_gold_release
from utux.evalkit.splits import split_report

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "gold_release" / "synthetic_release.jsonl"
)

DEV = {
    # Per claim: G9000 verified, G9001 partially_supported, G9007 verified.
    "gold_status": {
        "verified": 2,
        "partially_supported": 1,
        "contradicted": 0,
        "insufficient_evidence": 0,
    },
    # Per pair: only G9001-c1-s1 has a flag.
    "scope_flag": {
        "direction_mismatch": 0,
        "causal_overreach": 0,
        "magnitude_mismatch": 0,
        "overgeneralisation": 1,
        "metric_mismatch": 0,
        "certainty_escalation": 0,
        "missing_comparator": 0,
    },
    # Per item: G9000 ml, G9001 ml, G9007 biomedicine.
    "domain": {"ml": 2, "biomedicine": 1},
    # Per pair: G9000 full text, G9001 full text, G9007 abstract.
    "evidence_text": {"abstract": 1, "full_text": 2},
    # Per item: G9000 and G9007 natural, G9001 perturbed.
    "item_source": {"natural": 2, "perturbed": 1, "system_generated": 0},
    # Per item: G9001 negation_or_hedge; G9000 and G9007 none.
    "hard_case": {
        "abstract_vs_full_text": 0,
        "number_wrong_context": 0,
        "conflict_within_source": 0,
        "true_but_not_in_source": 0,
        "attributed_prior_work": 0,
        "heavy_paraphrase": 0,
        "negation_or_hedge": 1,
        "none": 2,
    },
}

TEST = {
    # Per claim: verified G9002, G9005, G9009; partially_supported G9008;
    # contradicted G9003, G9006; insufficient_evidence G9004.
    "gold_status": {
        "verified": 3,
        "partially_supported": 1,
        "contradicted": 2,
        "insufficient_evidence": 1,
    },
    # Per pair: direction_mismatch on G9003-c1-s1, G9003-c1-s2 and G9006-c1-s1;
    # magnitude_mismatch on G9003-c1-s2; metric_mismatch on G9008-c1-s1.
    "scope_flag": {
        "direction_mismatch": 3,
        "causal_overreach": 0,
        "magnitude_mismatch": 1,
        "overgeneralisation": 0,
        "metric_mismatch": 1,
        "certainty_escalation": 0,
        "missing_comparator": 0,
    },
    # Per item: biomedicine G9002, G9004; ml the other five.
    "domain": {"ml": 5, "biomedicine": 2},
    # Per pair (8): abstract G9002, G9003-c1-s2, G9004; full text the other five.
    "evidence_text": {"abstract": 3, "full_text": 5},
    # Per item: perturbed G9006, system_generated G9003, natural the other five.
    "item_source": {"natural": 5, "perturbed": 1, "system_generated": 1},
    # Per item: G9004 abstract_vs_full_text; the other six none.
    "hard_case": {
        "abstract_vs_full_text": 1,
        "number_wrong_context": 0,
        "conflict_within_source": 0,
        "true_but_not_in_source": 0,
        "attributed_prior_work": 0,
        "heavy_paraphrase": 0,
        "negation_or_hedge": 0,
        "none": 6,
    },
}


def test_report_counts_equal_the_hand_counted_values() -> None:
    report = split_report(read_gold_release(FIXTURE)).to_json()
    assert report == {
        "items": {"dev": 3, "test": 7},
        # 3 of 10 items.
        "dev_share": 0.3,
        "dev": DEV,
        "test": TEST,
    }


def test_report_lines_show_the_counts_and_no_item_text() -> None:
    items = read_gold_release(FIXTURE)
    lines = split_report(items).lines()
    assert lines[0] == "Items: dev 3, test 7. Dev share: 0.300"
    assert "Gold status (per claim):" in lines
    assert "  verified: dev 2, test 3" in lines
    assert "Scope flag (per pair):" in lines
    assert "  direction_mismatch: dev 0, test 3" in lines
    assert "Domain (per item):" in lines
    assert "Evidence text (per pair):" in lines
    assert "  abstract: dev 1, test 3" in lines
    assert "Item source (per item):" in lines
    assert "Hard case (per item):" in lines
    assert "  none: dev 2, test 6" in lines
    text = "\n".join(lines)
    for item in items:
        assert item.item_id not in text
        assert item.text_unit not in text
        for claim in item.claims:
            assert claim.text not in text
            for pair in claim.pairs:
                assert pair.source_id not in text
                assert pair.source_group not in text
    assert "synthetic" not in text.lower()


def test_report_of_an_empty_release_is_refused() -> None:
    with pytest.raises(GoldSetError, match="no items"):
        split_report(())


def test_the_report_needs_the_split_of_every_item() -> None:
    items = read_gold_release(FIXTURE)
    unset = [items[0].model_copy(update={"split": None}), *items[1:]]
    with pytest.raises(GoldSetError, match="split"):
        split_report(unset)
