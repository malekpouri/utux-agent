"""Recording a run that has ended: its manifest and its result records.

`record_run` runs only after a run, since it takes the run's `RunResult`.
It writes `runs/<run_id>/manifest.json`, then turns each entry of the run's
`outputs/metrics.json` into one line of `results.jsonl` with a new result id,
the run's id, and the metrics file as source. Both files are written with
the atomic writer. The caller holds the project lock.

Numbers never come from model text: only the file the step's code wrote is
read, and only if it is still the file the run reported. A run that a limit
stopped gets its manifest but no records, even if it wrote `metrics.json`:
a file that may be cut off mid-write cannot become a published number.
"""

from dataclasses import dataclass
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

STOPPED_BY_LIMIT = "stopped_by_limit"
"""Reason: a limit stopped the run, so its metrics are not recorded."""

NO_METRICS_FILE = "no_metrics_file"
"""Reason: the run wrote no metrics file."""


@dataclass(frozen=True)
class RunRecording:
    """What `record_run` recorded.

    Attributes:
        records: The new result records, in the order of the metrics file.
        not_recorded: Why there are none, as a stable code
            (`stopped_by_limit` or `no_metrics_file`), or None when the
            metrics file was recorded, even with no entries.
    """

    records: tuple[ResultRecord, ...]
    not_recorded: str | None


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
    project: Path,
    step: ExecutionStep,
    result: RunResult,
    manifest: RunManifest,
    *,
    root: Path | None = None,
) -> RunRecording:
    """Write the manifest of an ended run, then its result records.

    `root` is where the run's files are and where the manifest and the new
    `results.jsonl` are written, with the project's own paths below it; by
    default the project itself. A node of the workflow passes its staging
    area, and moves the files into the project when it completes. Existing
    records and manifests are always read from the project.

    Returns:
        The new records, or the reason there are none: the run was stopped
        by a limit, or it wrote no `metrics.json`. Neither is an error.

    Raises:
        ResultRecordingError: The manifest is of another run, it states
            another exit status or limit than the run's, its outputs differ
            from the run's, the run already has a manifest, or the
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
    if (manifest.exit_status, manifest.stopped_by) != (result.exit_status, result.stopped_by):
        raise ResultRecordingError(
            "the manifest states another way the run ended than its result: exit status "
            f"{manifest.exit_status} and limit {manifest.stopped_by}, not "
            f"{result.exit_status} and {result.stopped_by}"
        )
    if manifest.outputs != manifest_outputs(step, result):
        raise ResultRecordingError("the manifest's outputs differ from the files the run wrote")
    manifest_path = project / "runs" / step.run_id / "manifest.json"
    if manifest_path.exists():
        raise ResultRecordingError(f"run {step.run_id} already has a manifest; it is recorded once")
    target = project if root is None else root
    reported = {file.path: file.content_hash for file in result.output_files}
    metrics_path = target / step.output_directory / METRICS_FILE
    source = f"{step.output_directory}/{METRICS_FILE}"
    if (
        result.stopped_by is None
        and METRICS_FILE in reported
        and hash_file(metrics_path) != reported[METRICS_FILE]
    ):
        raise ResultRecordingError(
            f"{source} changed after the run; only the file the run wrote is recorded"
        )

    written_manifest = target / "runs" / step.run_id / "manifest.json"
    written_manifest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(written_manifest, manifest.to_json())
    if result.stopped_by is not None:
        return RunRecording((), STOPPED_BY_LIMIT)
    if METRICS_FILE not in reported:
        return RunRecording((), NO_METRICS_FILE)

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
            target / RESULTS_FILE, prefix + "".join(r.to_json_line() for r in records)
        )
    return RunRecording(records, None)
