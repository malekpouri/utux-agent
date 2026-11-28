"""M0-15c: the v0 sample with its splits, and the maintainer's blind audit, on synthetic items.

Sizes are made small for the synthetic corpus; the command line uses the
strategy's sizes.
"""

import csv
import io
from pathlib import Path

import pytest
from synthetic_gold_corpus import synthetic_corpus

from utux.errors import GoldSetError
from utux.evalkit.audit import AUDIT_COLUMNS, KAPPA_FLOOR, export_audit, score_audit
from utux.evalkit.gold import (
    Confirmation,
    Domain,
    GoldItem,
    GoldStatus,
    Origin,
    PerturbationRecord,
    PublicDataset,
    check_release,
)
from utux.evalkit.perturb import PerturbationRun, build_rule_perturbations
from utux.evalkit.sample import SampleSizes, sample_v0, select_imported

SMALL = SampleSizes(scifact_per_status=1, sciclaimeval_ml_per_status=1, perturbations=3)


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[tuple[GoldItem, ...], dict[str, str]]:
    return synthetic_corpus(tmp_path)


def _with_model_check(run: PerturbationRun) -> tuple[GoldItem, ...]:
    """Synthetic stand-ins for model-written items: rule children relabelled as model_check."""
    changed = []
    for child in run.items:
        assert isinstance(child.hidden, PerturbationRecord)
        hidden = child.hidden.model_copy(update={"confirmation": Confirmation.MODEL_CHECK})
        changed.append(child.model_copy(update={"hidden": hidden}))
    return tuple(changed)


# The sample ------------------------------------------------------------------------


def test_the_imported_selection_is_stratified_and_fixed_by_the_seed(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, _ = corpus
    chosen = select_imported(items, SMALL, seed=11)
    assert chosen == select_imported(items, SMALL, seed=11)
    scifact = [i for i in chosen if i.provenance and i.provenance.dataset is PublicDataset.SCIFACT]
    statuses = sorted(i.claims[0].status.value for i in scifact)
    assert statuses == ["contradicted", "insufficient_evidence", "verified"]
    others = [i for i in chosen if i not in scifact]
    assert {i.domain for i in others} == {Domain.ML}
    assert sorted(i.claims[0].status.value for i in others) == ["contradicted", "verified"]


def test_too_few_items_for_a_stratum_is_an_error(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, _ = corpus
    with pytest.raises(GoldSetError, match="verified"):
        select_imported(items, SampleSizes(scifact_per_status=5), seed=11)


def test_the_v0_sample_takes_perturbations_of_chosen_parents_and_splits_by_group(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = corpus
    perturbed = build_rule_perturbations(items, texts, seed=7).items
    sample = sample_v0(items, perturbed, SMALL, seed=11, dev_share=0.3)
    chosen = {i.item_id for i in sample.items if i.origin is Origin.PUBLIC}
    children = [i for i in sample.items if i.origin is Origin.PERTURBED]
    assert 0 < len(children) <= SMALL.perturbations
    for child in children:
        assert isinstance(child.hidden, PerturbationRecord)
        assert child.hidden.source_item in chosen
    assert all(i.split is not None for i in sample.items)
    by_id = {i.item_id: i for i in sample.items}
    for child in children:
        assert isinstance(child.hidden, PerturbationRecord)
        assert child.split is by_id[child.hidden.source_item].split
    assert {p.code for p in check_release(sample.items).problems} == set()
    assert sample == sample_v0(items, perturbed, SMALL, seed=11, dev_share=0.3)


def test_the_sample_report_is_counts_only(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = corpus
    perturbed = build_rule_perturbations(items, texts, seed=7).items
    report = sample_v0(items, perturbed, SMALL, seed=11, dev_share=0.3).report()
    assert set(report) >= {"seed", "dev_share", "items", "by_split"}
    assert set(report["by_split"]) <= {"dev", "test"}
    for counts in report["by_split"].values():
        assert set(counts) == {"origin", "status", "domain", "confirmation"}
    assert "Drug" not in str(report)


# The audit -------------------------------------------------------------------------


def _audit_items(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> tuple[tuple[GoldItem, ...], dict[str, str]]:
    items, texts = corpus
    model_items = _with_model_check(build_rule_perturbations(items, texts, seed=7))
    return items + model_items, texts


def test_the_audit_sheet_is_blind(corpus: tuple[tuple[GoldItem, ...], dict[str, str]]) -> None:
    items, texts = _audit_items(corpus)
    sheet, key = export_audit(items, texts, seed=5, model_written=2, imported=1)
    rows = list(csv.DictReader(io.StringIO(sheet)))
    assert AUDIT_COLUMNS == ("row", "claim", "evidence", "status")
    assert list(rows[0]) == list(AUDIT_COLUMNS)
    assert len(rows) == 3
    assert all(row["status"] == "" for row in rows)
    for row in rows:
        assert row["claim"]
        assert row["evidence"]
    # No item id, origin, constructed label or flag in the sheet.
    for word in ("G1", "G2", "G3", "perturbed", "public", "verified", "contradicted", "mismatch"):
        assert word not in sheet.replace("Drug", "")
    assert sorted(key) == sorted(row["row"] for row in rows)
    assert export_audit(items, texts, seed=5, model_written=2, imported=1) == (sheet, key)


def test_the_audit_needs_enough_items_of_each_kind(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = corpus
    with pytest.raises(GoldSetError, match="model_check"):
        export_audit(items, texts, seed=5, model_written=2, imported=1)


def _filled(sheet: str, answers: dict[str, str]) -> str:
    rows = list(csv.DictReader(io.StringIO(sheet)))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(AUDIT_COLUMNS))
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, "status": answers[row["row"]]})
    return out.getvalue()


def test_the_score_is_cohens_kappa_and_upgrades_confirmed_items(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = _audit_items(corpus)
    sheet, key = export_audit(items, texts, seed=5, model_written=2, imported=1)
    by_id = {i.item_id: i for i in items}
    constructed = {row: by_id[item_id].claims[0].status.value for row, item_id in key.items()}
    result = score_audit(items, key, _filled(sheet, constructed), annotator="a01")
    assert result.agreed == 3
    assert result.disagreed == 0
    assert result.below_floor is False
    upgraded = {i.item_id: i for i in result.items}
    for _row, item_id in key.items():
        hidden = upgraded[item_id].hidden
        if isinstance(hidden, PerturbationRecord):
            assert (hidden.confirmation, hidden.confirmed_by) == (Confirmation.AUDIT, "a01")
    # Labels never change.
    assert [i.claims[0].status for i in result.items] == [i.claims[0].status for i in items]


def test_kappa_below_the_floor_is_flagged_and_disagreements_are_not_upgraded(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]],
) -> None:
    items, texts = _audit_items(corpus)
    sheet, key = export_audit(items, texts, seed=5, model_written=2, imported=1)
    by_id = {i.item_id: i for i in items}
    statuses = [s.value for s in GoldStatus]
    wrong = {
        row: next(s for s in statuses if s != by_id[item_id].claims[0].status.value)
        for row, item_id in key.items()
    }
    result = score_audit(items, key, _filled(sheet, wrong), annotator="a01")
    assert KAPPA_FLOOR == 0.6
    assert result.disagreed == 3
    assert result.below_floor is True
    assert all(
        not isinstance(i.hidden, PerturbationRecord)
        or i.hidden.confirmation is not Confirmation.AUDIT
        for i in result.items
    )


@pytest.mark.parametrize("answer", ["", "maybe", "unverified"])
def test_an_unfilled_or_unknown_status_is_refused(
    corpus: tuple[tuple[GoldItem, ...], dict[str, str]], answer: str
) -> None:
    items, texts = _audit_items(corpus)
    sheet, key = export_audit(items, texts, seed=5, model_written=2, imported=1)
    with pytest.raises(GoldSetError, match="status"):
        score_audit(items, key, _filled(sheet, dict.fromkeys(key, answer)), annotator="a01")
