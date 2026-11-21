"""M1-09: result records from a run's `outputs/metrics.json`.

Numbers never come from model text: the step's code writes the metrics file
and utux turns each entry into one result record. The runs here are played
by the scripted executor; nothing is executed.
"""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError, ResultRecordingError
from utux.executors.scripted import ScriptedExecutor, ScriptedRun
from utux.interfaces.executor import ExecutionStep, ResourceLimits, RunResult
from utux.schemas.result_record import ResultRecord
from utux.schemas.run_manifest import RunManifest
from utux.workspace import results as results_module
from utux.workspace.results import METRICS_FILE, manifest_outputs, record_run
from utux.workspace.validation import validate_project

VALID = Path(__file__).resolve().parents[1] / "fixtures" / "projects" / "valid_full"
OUTPUT = "runs/r013/outputs"

METRICS = {
    "schema_version": 1,
    "entries": [
        {
            "metric": "AUC",
            "value": 0.91,
            "unit": "score",
            "dataset": "dataset_x",
            "model": "model_b",
            "split": "test",
            "tolerance": 0.005,
        },
        {
            "metric": "rows",
            "value": 1200.0,
            "unit": "count",
            "dataset": "dataset_x",
            "model": None,
            "split": None,
            "tolerance": 0.0,
        },
    ],
}


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    return project


def _step() -> ExecutionStep:
    return ExecutionStep(
        run_id="r013",
        command=("python", "code/train.py"),
        image_digest="sha256:" + "a" * 64,
        read_only_paths=("code",),
        output_directory=OUTPUT,
        limits=ResourceLimits(),
        timeout_seconds=60.0,
        environment={},
    )


def _run(project: Path, files: dict[str, bytes]) -> RunResult:
    return ScriptedExecutor(project, [ScriptedRun(files=files)]).run(_step())


def _metrics_bytes(document: dict[str, Any] = METRICS) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def _manifest(project: Path, result: RunResult, **changes: Any) -> RunManifest:
    document = json.loads((project / "runs" / "r012" / "manifest.json").read_text("utf-8"))
    document.update(
        run_id=result.run_id,
        outputs=[o.model_dump(mode="json") for o in manifest_outputs(_step(), result)],
        started_at=result.started_at,
        ended_at=result.ended_at,
        exit_status=result.exit_status,
        **changes,
    )
    return RunManifest.from_json(json.dumps(document))


def _lines(project: Path) -> list[str]:
    return (project / "results.jsonl").read_text(encoding="utf-8").splitlines()


def test_each_entry_becomes_one_record_with_a_new_id(project: Path) -> None:
    before = _lines(project)
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    records = record_run(project, _step(), result, _manifest(project, result))
    assert [r.id for r in records] == ["R0043", "R0044"]
    first, second = records
    assert (first.metric, first.value, first.unit, first.dataset) == (
        "AUC",
        0.91,
        "score",
        "dataset_x",
    )
    assert (first.model, first.split, first.tolerance) == ("model_b", "test", 0.005)
    assert (second.model, second.split) == (None, None)
    assert all(r.run_id == "r013" for r in records)
    assert all(r.source == f"{OUTPUT}/{METRICS_FILE}" for r in records)
    # The existing lines are kept byte for byte; the new ones follow.
    lines = _lines(project)
    assert lines[: len(before)] == before
    assert [ResultRecord.from_json(line) for line in lines[len(before) :]] == list(records)


def test_the_manifest_is_written_and_the_project_stays_valid(project: Path) -> None:
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    manifest = _manifest(project, result)
    record_run(project, _step(), result, manifest)
    written = RunManifest.from_json((project / "runs" / "r013" / "manifest.json").read_text("utf-8"))
    assert written == manifest
    report = validate_project(project)
    assert report.problems == ()


def test_the_first_record_of_a_project_is_r0001(project: Path) -> None:
    (project / "results.jsonl").write_bytes(b"")
    (project / "claims.jsonl").write_bytes(b"")
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    records = record_run(project, _step(), result, _manifest(project, result))
    assert [r.id for r in records] == ["R0001", "R0002"]


def test_an_invalid_metrics_file_fails_with_its_problems_and_writes_no_record(
    project: Path,
) -> None:
    before = (project / "results.jsonl").read_bytes()
    bad = {"schema_version": 1, "entries": [{**METRICS["entries"][0], "value": "0.91"}]}
    result = _run(project, {METRICS_FILE: _metrics_bytes(bad)})
    with pytest.raises(ContractValidationError) as caught:
        record_run(project, _step(), result, _manifest(project, result))
    assert [(p.field, p.code) for p in caught.value.problems] == [
        ("entries.0.value", "float_type")
    ]
    assert caught.value.source == f"{OUTPUT}/{METRICS_FILE}"
    assert (project / "results.jsonl").read_bytes() == before
    # The run ended, so its manifest is still written.
    assert (project / "runs" / "r013" / "manifest.json").is_file()


def test_a_run_without_a_metrics_file_has_no_records(project: Path) -> None:
    before = (project / "results.jsonl").read_bytes()
    result = _run(project, {"log.txt": b"synthetic\n"})
    assert record_run(project, _step(), result, _manifest(project, result)) == ()
    assert (project / "results.jsonl").read_bytes() == before


def test_a_metrics_file_changed_after_the_run_is_refused(project: Path) -> None:
    before = (project / "results.jsonl").read_bytes()
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    (project / OUTPUT / METRICS_FILE).write_bytes(_metrics_bytes() + b" ")
    with pytest.raises(ResultRecordingError, match="changed after the run"):
        record_run(project, _step(), result, _manifest(project, result))
    assert (project / "results.jsonl").read_bytes() == before
    assert not (project / "runs" / "r013" / "manifest.json").exists()


def test_a_manifest_of_another_run_is_refused(project: Path) -> None:
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    manifest = _manifest(project, result, run_id="r099")
    with pytest.raises(ResultRecordingError, match="r099"):
        record_run(project, _step(), result, manifest)
    assert not (project / "runs" / "r013" / "manifest.json").exists()


def test_a_manifest_whose_outputs_differ_from_the_run_is_refused(project: Path) -> None:
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    manifest = _manifest(project, result, outputs=[])
    with pytest.raises(ResultRecordingError, match="outputs"):
        record_run(project, _step(), result, manifest)


def test_a_run_is_recorded_once(project: Path) -> None:
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    manifest = _manifest(project, result)
    record_run(project, _step(), result, manifest)
    lines = _lines(project)
    with pytest.raises(ResultRecordingError, match="already has a manifest"):
        record_run(project, _step(), result, manifest)
    assert _lines(project) == lines


def test_an_invalid_results_file_is_not_added_to(project: Path) -> None:
    (project / "results.jsonl").write_text("not json\n", encoding="utf-8")
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    with pytest.raises(ContractValidationError):
        record_run(project, _step(), result, _manifest(project, result))
    assert _lines(project) == ["not json"]


def test_both_files_are_written_with_the_atomic_writer(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Path] = []
    original = results_module.atomic_write_text

    def recording(path: Path, text: str) -> None:
        written.append(path)
        original(path, text)

    monkeypatch.setattr(results_module, "atomic_write_text", recording)
    result = _run(project, {METRICS_FILE: _metrics_bytes()})
    record_run(project, _step(), result, _manifest(project, result))
    assert written == [project / "runs" / "r013" / "manifest.json", project / "results.jsonl"]


def test_manifest_outputs_name_each_output_by_its_project_path(project: Path) -> None:
    content = _metrics_bytes()
    result = _run(project, {METRICS_FILE: content})
    (output,) = manifest_outputs(_step(), result)
    assert output.path == f"{OUTPUT}/{METRICS_FILE}"
    assert output.hash == "sha256:" + hashlib.sha256(content).hexdigest()
