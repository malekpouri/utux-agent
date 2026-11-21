"""Recording a run that has ended: its manifest and its result records.

`record_run` runs only after a run, since it takes the run's `RunResult`.
It writes `runs/<run_id>/manifest.json`, then turns each entry of the run's
`outputs/metrics.json` into one line of `results.jsonl` with a new result id,
the run's id, and the metrics file as source. Both files are written with
the atomic writer. The caller holds the project lock.

Numbers never come from model text: only the file the step's code wrote is
read, and only if it is still the file the run reported.
"""

from pathlib import Path

from utux.errors import ResultRecordingError
from utux.interfaces.executor import ExecutionStep, RunResult
from utux.schemas.json_io import parse_json
from utux.schemas.metrics import MetricsFile
from utux.schemas.result_record import ResultRecord
from utux.schemas.run_manifest import FileRef, RunManifest
from utux.workspace.atomic import atomic_write_text
from utux.workspace.hashing import hash_file
from utux.workspace.layout import RESULTS_FILE

METRICS_FILE = "metrics.json"
"""The name of the metrics file in a step's output directory."""

_ID_DIGITS = 4


def manifest_outputs(step: ExecutionStep, result: RunResult) -> tuple[FileRef, ...]:
    """The outputs of a run as the run manifest lists them: project path and hash."""
    return tuple(
        FileRef(path=f"{step.output_directory}/{file.path}", hash=file.content_hash)
        for file in result.output_files
    )


def _existing_records(project: Path) -> tuple[str, list[ResultRecord]]:
    """Read `results.jsonl`; every line must be a valid record."""
    path = project / RESULTS_FILE
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    records = [
        ResultRecord.validate_document(parse_json(line, RESULTS_FILE), f"{RESULTS_FILE}:{number}")
        for number, line in enumerate(text.split("\n"), start=1)
        if line
    ]
    return text, records


def _next_ids(records: list[ResultRecord], count: int) -> list[str]:
    numbers = [int(record.id[1:]) for record in records]
    width = max([_ID_DIGITS, *(len(record.id) - 1 for record in records)])
    start = max(numbers, default=0) + 1
    return [f"R{number:0{width}d}" for number in range(start, start + count)]


def record_run(
    project: Path, step: ExecutionStep, result: RunResult, manifest: RunManifest
) -> tuple[ResultRecord, ...]:
    """Write the manifest of an ended run, then its result records.

    Returns:
        The new records, in the order of the metrics file. Empty if the run
        wrote no `metrics.json`.

    Raises:
        ResultRecordingError: The manifest is of another run, its outputs
            differ from the run's, the run already has a manifest, or the
            metrics file changed after the run. Nothing is written.
        ContractValidationError: The metrics file, or a line of
            `results.jsonl`, is invalid; the problems are those of the schema.
            The manifest is written, since the run ended; no record is.
    """
    if not (manifest.run_id == step.run_id == result.run_id):
        raise ResultRecordingError(
            f"the manifest is of run {manifest.run_id}, the step and result of run "
            f"{step.run_id} and {result.run_id}"
        )
    if manifest.outputs != manifest_outputs(step, result):
        raise ResultRecordingError("the manifest's outputs differ from the files the run wrote")
    manifest_path = project / "runs" / step.run_id / "manifest.json"
    if manifest_path.exists():
        raise ResultRecordingError(f"run {step.run_id} already has a manifest; it is recorded once")
    reported = {file.path: file.content_hash for file in result.output_files}
    metrics_path = project / step.output_directory / METRICS_FILE
    source = f"{step.output_directory}/{METRICS_FILE}"
    if METRICS_FILE in reported and hash_file(metrics_path) != reported[METRICS_FILE]:
        raise ResultRecordingError(
            f"{source} changed after the run; only the file the run wrote is recorded"
        )

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(manifest_path, manifest.to_json())
    if METRICS_FILE not in reported:
        return ()

    metrics = MetricsFile.validate_document(
        parse_json(metrics_path.read_text(encoding="utf-8"), source), source
    )
    text, existing = _existing_records(project)
    records = tuple(
        ResultRecord(
            schema_version=ResultRecord.SCHEMA_VERSION,
            id=record_id,
            metric=entry.metric,
            value=entry.value,
            unit=entry.unit,
            dataset=entry.dataset,
            model=entry.model,
            split=entry.split,
            run_id=step.run_id,
            source=source,
            tolerance=entry.tolerance,
        )
        for record_id, entry in zip(
            _next_ids(existing, len(metrics.entries)), metrics.entries, strict=True
        )
    )
    if records:
        prefix = text if not text or text.endswith("\n") else text + "\n"
        atomic_write_text(
            project / RESULTS_FILE, prefix + "".join(r.to_json_line() for r in records)
        )
    return records
