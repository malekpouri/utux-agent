"""M1-09: the schema of `outputs/metrics.json`, which a step's code writes."""

import re
from pathlib import Path

import pytest
from contract_checks import Row, check_invalid, check_round_trip, check_table, valid_paths

from utux.schemas.metrics import MetricsFile, load_metrics_file

CONTRACT = "metrics"
REPO_ROOT = Path(__file__).resolve().parents[2]

INVALID: list[Row] = [
    ("missing_entries.json", "entries", "missing"),
    ("entry_without_unit.json", "entries.0.unit", "missing"),
    ("value_is_text.json", "entries.0.value", "float_type"),
    ("negative_tolerance.json", "entries.0.tolerance", "greater_than_equal"),
    ("unknown_key.json", "entries.0.comment", "unknown_key"),
    ("duplicate_entry.json", "entries.1", "duplicate_entry"),
    ("entries_not_a_list.json", "entries", "tuple_type"),
    ("empty_metric.json", "entries.0.metric", "string_too_short"),
    ("newer_schema_version.json", "schema_version", "schema_version_newer"),
    ("malformed_json.json", "<document>", "invalid_json"),
]


def test_a_valid_file_reads_every_field() -> None:
    metrics = load_metrics_file(valid_paths(CONTRACT)[1])
    first, second = metrics.entries
    assert (first.metric, first.value, first.unit) == ("AUC", 0.95, "score")
    assert (first.dataset, first.model, first.split, first.tolerance) == (
        "dataset_x",
        "model_a",
        "test",
        0.005,
    )
    assert second.model is None
    assert second.split is None


def test_an_empty_list_is_valid() -> None:
    assert load_metrics_file(valid_paths(CONTRACT)[0]).entries == ()


@pytest.mark.parametrize("path", valid_paths(CONTRACT), ids=lambda p: p.name)
def test_round_trip(path: Path) -> None:
    check_round_trip(MetricsFile, load_metrics_file, path)


def test_invalid_fixture_table() -> None:
    check_table(CONTRACT, INVALID)


@pytest.mark.parametrize("row", INVALID, ids=[row[0] for row in INVALID])
def test_invalid_fixture_fails_for_its_own_reason(row: Row) -> None:
    check_invalid(CONTRACT, load_metrics_file, row)


@pytest.mark.parametrize(
    ("document", "start"),
    [("docs/results.md", "## The metrics file"), ("docs/spec.md", "### Result records")],
)
def test_the_examples_of_the_documents_are_valid(document: str, start: str) -> None:
    section = (REPO_ROOT / document).read_text(encoding="utf-8").split(start, 1)[1]
    blocks = re.findall(r"```json\n(.*?)```", section, flags=re.DOTALL)
    examples = [block for block in blocks if '"entries"' in block]
    assert examples, document
    metrics = MetricsFile.from_json(examples[0], source=document)
    assert metrics.entries
