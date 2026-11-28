"""M0-13a: the checks across a gold release, and the group-aware split.

The release is synthetic; its items and how they are linked are listed, by
hand, in `tests/fixtures/gold_release/README.md`. Every expected value below
follows from that table.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError, GoldSetError
from utux.evalkit.gold import (
    GoldItem,
    GoldSplit,
    check_release,
    guideline_status,
    load_gold_item,
    read_gold_release,
)
from utux.evalkit.splits import assign_splits, split_groups

FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "gold_release" / "synthetic_release.jsonl"
)
OTHER_HASH = "sha256:" + "0" * 64

# The items that must share a split, from the README table.
GROUPS = [
    frozenset({"G9000", "G9001"}),
    frozenset({"G9002", "G9003", "G9004"}),
    frozenset({"G9005", "G9006"}),
    frozenset({"G9007"}),
    frozenset({"G9008"}),
    frozenset({"G9009"}),
]


def _items() -> list[GoldItem]:
    return list(read_gold_release(FIXTURE))


def _changed(items: list[GoldItem], item_id: str, change: dict[str, Any]) -> list[GoldItem]:
    """Return the release with one item changed through its JSON form."""
    result = []
    for item in items:
        if item.item_id == item_id:
            document = json.loads(item.to_json_line())
            _apply(document, change)
            item = GoldItem.validate_document(document, item_id)
        result.append(item)
    return result


def _apply(document: dict[str, Any], change: dict[str, Any]) -> None:
    for path, value in change.items():
        target: Any = document
        *parents, last = path.split(".")
        for part in parents:
            target = target[int(part)] if isinstance(target, list) else target[part]
        target[last] = value


def _problems(items: list[GoldItem]) -> list[tuple[str, str]]:
    return [(problem.field, problem.code) for problem in check_release(items).problems]


# Reading


def test_release_is_read_in_order() -> None:
    assert [item.item_id for item in _items()] == [f"G90{n:02d}" for n in range(10)]


def test_release_file_reports_the_line_of_each_invalid_item(tmp_path: Path) -> None:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[2] = lines[2].replace('"split": "test"', '"split": "train"')
    lines[4] = "\n"
    path = tmp_path / "synthetic_release.jsonl"
    path.write_text("".join(lines), encoding="utf-8")
    with pytest.raises(ContractValidationError) as caught:
        read_gold_release(path)
    assert [(problem.field, problem.code) for problem in caught.value.problems] == [
        ("line 3, split", "enum"),
        ("line 5", "empty_line"),
    ]
    assert caught.value.source == str(path)


def test_empty_release_file_has_no_items(tmp_path: Path) -> None:
    path = tmp_path / "synthetic_empty.jsonl"
    path.write_text("", encoding="utf-8")
    assert read_gold_release(path) == ()


# The release check


def test_fixture_release_passes_the_check() -> None:
    assert _problems(_items()) == []


def test_perturbed_item_in_another_split_than_its_origin() -> None:
    # G9001 alone uses sg-synthetic-b, so only the origin rule is broken.
    items = _changed(_items(), "G9001", {"split": "test"})
    assert _problems(items) == [("G9001.split", "split_differs_from_origin")]


def test_source_group_in_both_splits_is_reported_once_per_group() -> None:
    # G9003 in dev: sg-synthetic-c starts with G9002 (test), so G9003 is
    # reported; sg-synthetic-d starts with G9003 (dev), so G9004 is reported.
    items = _changed(_items(), "G9003", {"split": "dev"})
    assert _problems(items) == [
        ("G9003.claims.0.pairs.0.source_group", "source_group_in_both_splits"),
        ("G9004.claims.0.pairs.0.source_group", "source_group_in_both_splits"),
    ]


def test_duplicate_item_id() -> None:
    items = _items()
    assert _problems([*items, items[9]]) == [("G9009.item_id", "duplicate_item_id")]


def test_origin_that_is_not_in_the_release() -> None:
    items = _changed(_items(), "G9006", {"hidden.source_item": "G9099"})
    assert _problems(items) == [("G9006.hidden.source_item", "unknown_source_item")]


def test_origin_that_is_not_a_natural_item() -> None:
    # G9003 is system-generated and in test, like G9006.
    items = _changed(_items(), "G9006", {"hidden.source_item": "G9003"})
    assert _problems(items) == [("G9006.hidden.source_item", "source_item_not_natural")]


def test_items_of_one_release_share_its_version() -> None:
    items = _changed(_items(), "G9005", {"gold_version": "0.1"})
    assert _problems(items) == [("G9005.gold_version", "gold_version_mismatch")]


def test_one_source_belongs_to_one_group() -> None:
    # G9009 cites the source of G9008 but puts it in its own group.
    cited = ["synthetic:sg-synthetic-g-paper"]
    items = _changed(
        _items(),
        "G9009",
        {
            "claims.0.pairs.0.source_id": cited[0],
            # The extracted claims cite the same source, so the item stays valid.
            "annotation.claim_extraction.raw.a91.0.citations": cited,
            "annotation.claim_extraction.raw.a92.0.citations": cited,
        },
    )
    assert _problems(items) == [("G9009.claims.0.pairs.0.source_group", "source_group_mismatch")]


def test_one_source_has_one_text_hash() -> None:
    # G9002 and G9003 both cite synthetic:sg-synthetic-c-paper.
    items = _changed(_items(), "G9003", {"claims.0.pairs.0.text_hash": OTHER_HASH})
    assert _problems(items) == [("G9003.claims.0.pairs.0.text_hash", "text_hash_mismatch")]


# The split


def test_split_groups_are_those_worked_out_by_hand() -> None:
    assert split_groups(_items()) == GROUPS


def test_split_groups_join_a_perturbed_item_and_its_origin_with_no_shared_source() -> None:
    items = _items()
    g9000, g9001 = items[0], items[1]
    assert {pair.source_group for claim in g9000.claims for pair in claim.pairs} == {
        "sg-synthetic-a"
    }
    assert {pair.source_group for claim in g9001.claims for pair in claim.pairs} == {
        "sg-synthetic-b"
    }
    assert frozenset({"G9000", "G9001"}) in split_groups(items)


@pytest.mark.parametrize("seed", range(20))
def test_assigned_splits_keep_every_group_together(seed: int) -> None:
    items = _items()
    splits = assign_splits(items, dev_share=0.3, seed=seed)
    assert set(splits) == {item.item_id for item in items}
    for group in GROUPS:
        assert len({splits[item_id] for item_id in group}) == 1
    # 30 per cent of 10 items is 3. The groups have sizes 2, 3, 2, 1, 1, 1, so
    # a dev split of exactly 3 is always reachable, and the greedy fill always
    # reaches it (docs/gold-set.md).
    assert sum(split is GoldSplit.DEV for split in splits.values()) == 3
    applied = [item.model_copy(update={"split": splits[item.item_id]}) for item in items]
    assert check_release(applied).problems == ()


def test_same_seed_gives_the_same_split() -> None:
    items = _items()
    assert assign_splits(items, dev_share=0.3, seed=7) == assign_splits(
        items, dev_share=0.3, seed=7
    )


def test_different_seeds_can_give_different_splits() -> None:
    items = _items()
    results = {
        tuple(sorted(assign_splits(items, dev_share=0.3, seed=seed).items())) for seed in range(20)
    }
    assert len(results) > 1


def test_split_ignores_the_split_already_in_the_items() -> None:
    items = _items()
    flipped = [
        item.model_copy(
            update={"split": GoldSplit.DEV if item.split is GoldSplit.TEST else GoldSplit.TEST}
        )
        for item in items
    ]
    assert assign_splits(flipped, dev_share=0.3, seed=3) == assign_splits(
        items, dev_share=0.3, seed=3
    )


@pytest.mark.parametrize("share", [0.0, 1.0, -0.1, 1.5])
def test_dev_share_must_be_between_zero_and_one(share: float) -> None:
    with pytest.raises(GoldSetError, match="dev_share"):
        assign_splits(_items(), dev_share=share, seed=0)


def test_split_refuses_a_perturbed_item_whose_origin_is_missing() -> None:
    items = _items()
    without_origin = [item for item in items if item.item_id != "G9000"]
    with pytest.raises(GoldSetError, match=r"G9001.*G9000"):
        split_groups(without_origin)


# Departures from the guideline: reported, not failing


def _departures(items: list[GoldItem]) -> list[tuple[str, str]]:
    return [(d.field, d.code) for d in check_release(items).departures]


def test_fixture_release_follows_the_guideline_rules() -> None:
    # By guideline section 5.4, worked out from the README table: G9000,
    # G9002, G9005, G9007, G9009 entails, no flag: verified. G9001 partial
    # with a major flag, G9008 partial: partially_supported. G9003, G9006
    # contradicts only: contradicted. G9004 neutral only: insufficient_evidence.
    # Every reference status equals these, and no neutral pair has a flag.
    assert _departures(_items()) == []


def test_a_status_other_than_the_guideline_rules_give_is_a_departure() -> None:
    # G9008: one partial pair, so the rules give partially_supported.
    # The annotators agreed on partially_supported, so the departure is an
    # adjudication, with its reason.
    items = _changed(
        _items(),
        "G9008",
        {
            "claims.0.status": "verified",
            "claims.0.adjudicated": True,
            "claims.0.adjudication_reason": "Synthetic adjudication reason.",
            "annotation.adjudicator": "a90",
        },
    )
    assert _departures(items) == [("G9008.claims.0.status", "status_differs_from_rules")]
    assert _problems(items) == []


def test_flags_on_a_neutral_pair_are_a_departure() -> None:
    # G9004's only pair is neutral; a flag on it departs from section 5.3.
    # The rules still give insufficient_evidence (rule 8), as the reference.
    items = _changed(
        _items(),
        "G9004",
        {
            "claims.0.pairs.0.scope_flags": ["causal_overreach"],
            "claims.0.pairs.0.adjudicated": True,
            "claims.0.pairs.0.adjudication_reason": "Synthetic adjudication reason.",
            "annotation.adjudicator": "a90",
        },
    )
    assert _departures(items) == [("G9004.claims.0.pairs.0.scope_flags", "flags_on_neutral_pair")]


@pytest.mark.parametrize(
    ("labels", "flags", "expected"),
    [
        # Rule 1 is the claim without pairs, tested below.
        (["conflicting", "entails"], [[], []], "insufficient_evidence"),  # rule 2
        (["entails", "contradicts"], [[], []], "insufficient_evidence"),  # rule 3
        (["entails", "neutral"], [[], []], "verified"),  # rule 4, neutral ignored
        (["entails"], [["certainty_escalation"]], "verified"),  # rule 4, minor flag
        # Rule 5: a critical flag on a supporting pair holds the claim for a
        # human review, as RFC-001 section 4 does (maintainer, 2026-11-28).
        (["entails"], [["direction_mismatch"]], "insufficient_evidence"),  # rule 5
        (["entails"], [["causal_overreach"]], "insufficient_evidence"),  # rule 5
        (["partial", "neutral"], [["causal_overreach"], []], "insufficient_evidence"),  # rule 5
        (["entails"], [["overgeneralisation"]], "partially_supported"),  # rule 6, major flag
        (["partial", "neutral"], [[], []], "partially_supported"),  # rule 6
        (["contradicts", "neutral"], [[], []], "contradicted"),  # rule 7
        # A critical flag on a contradicting pair keeps contradicted (maintainer).
        (["contradicts"], [["magnitude_mismatch"]], "contradicted"),  # rule 7
        (["contradicts"], [["direction_mismatch"]], "contradicted"),  # rule 7
        (["neutral", "neutral"], [[], []], "insufficient_evidence"),  # rule 8
    ],
)
def test_guideline_status_rules(labels: list[str], flags: list[list[str]], expected: str) -> None:
    assert guideline_status(labels, flags) == expected


def test_guideline_status_of_a_claim_without_sources() -> None:
    assert guideline_status([], []) == "insufficient_evidence"  # rule 1


def test_an_item_without_a_split_is_not_frozen() -> None:
    items = _changed(_items(), "G9000", {"split": None})
    assert ("G9000.split", "split_not_set") in _problems(items)


def test_a_perturbation_may_be_made_from_a_public_item() -> None:
    # M0-15b review: perturbations of imported items carry the provenance.
    valid = Path(__file__).resolve().parents[1] / "fixtures" / "gold_item" / "valid"
    public = load_gold_item(valid / "synthetic_public_item.json")
    perturbed = load_gold_item(valid / "synthetic_public_perturbed_item.json")
    problems = [p for p in _problems([public, perturbed]) if p[1] != "split_not_set"]
    assert problems == []
