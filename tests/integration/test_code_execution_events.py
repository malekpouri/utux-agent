"""M1-15b: one code_execution event per execution run.

The model and executor are scripted (`workflow_scripts`); nothing runs.
"""

import json
import shutil
from pathlib import Path

import pytest
from workflow_scripts import (
    CODE,
    IMAGE,
    METHOD,
    METRICS,
    QUESTION,
    configure_models,
    services,
    switch_gates_off,
)

import utux.core.workflow as workflow
from utux.core.workflow import run_workflow
from utux.errors import ExecutorError, ExecutorUnavailableError
from utux.events.log import EventLog
from utux.executors.scripted import ScriptedRun, ScriptedUnavailable
from utux.schemas.common import LimitKind
from utux.schemas.event import Event, EventStatus, EventType, NewEvent
from utux.schemas.project_config import DataPolicy
from utux.workspace.hashing import hash_bytes, hash_file
from utux.workspace.project import init_project
from utux.workspace.validation import validate_project

PASSED = ScriptedRun(stdout=b"synthetic\n", files={"metrics.json": METRICS})


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    project = init_project(tmp_path / "p", budget_usd=5, data_policy=DataPolicy.LOCAL_ONLY)
    (project / "inputs" / "question.md").write_text(QUESTION, encoding="utf-8")
    configure_models(project)
    switch_gates_off(project)
    return project


def _executions(project: Path) -> list[Event]:
    return [e for e in EventLog(project / "events.jsonl") if e.type is EventType.CODE_EXECUTION]


def test_a_run_writes_one_code_execution_event_with_its_hashes(project: Path) -> None:
    outcome = run_workflow(project, services(project, executions=[PASSED]))
    (event,) = _executions(project)
    assert (event.status, event.status_reason) == (EventStatus.OK, None)
    assert event.stage is not None
    assert event.stage.value == "experiment"
    assert event.run_id == outcome.run_id
    assert event.data == {
        "execution_run_id": "r001",
        "image_digest": IMAGE,
        "exit_status": 0,
        "stopped_by": None,
    }
    assert event.input_hash == hash_file(project / "code" / "main.py")
    assert event.output_hash == hash_bytes(METRICS)
    assert event.duration_ms == 1000
    assert validate_project(project).problems == ()


def test_the_event_is_written_before_the_run_is_recorded(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[int] = []
    record_run = workflow.record_run

    def recording(*arguments: object, **keywords: object) -> object:
        seen.append(len(_executions(project)))
        return record_run(*arguments, **keywords)  # type: ignore[arg-type]

    monkeypatch.setattr(workflow, "record_run", recording)
    run_workflow(project, services(project, executions=[PASSED]))
    assert seen == [1]


@pytest.mark.parametrize(
    ("run", "reason"),
    [
        (ScriptedRun(exit_status=1, stderr=b"synthetic failure\n"), "nonzero_exit"),
        (ScriptedRun(exit_status=137), "nonzero_exit"),
        (ScriptedRun(exit_status=None, stopped_by=LimitKind.WALL_CLOCK), "limit_wall_clock"),
        (ScriptedRun(exit_status=137, stopped_by=LimitKind.MEMORY), "limit_memory"),
        (ScriptedRun(exit_status=None, stopped_by=LimitKind.OUTPUT_SIZE), "limit_output_size"),
    ],
)
def test_a_failed_run_is_an_error_with_its_reason(
    project: Path, run: ScriptedRun, reason: str
) -> None:
    # The failed run is routed back; the second run passes.
    run_workflow(project, services(project, (METHOD, CODE, CODE), executions=[run, PASSED]))
    failed, passed = _executions(project)
    assert (failed.status, failed.status_reason) == (EventStatus.ERROR, reason)
    assert failed.data["exit_status"] == run.exit_status
    assert failed.data["stopped_by"] == (None if run.stopped_by is None else run.stopped_by.value)
    assert failed.output_hash is None
    assert passed.status is EventStatus.OK
    assert validate_project(project).problems == ()


def test_a_run_that_cannot_start_for_want_of_an_executor_is_recorded(project: Path) -> None:
    with pytest.raises(ExecutorUnavailableError):
        run_workflow(project, services(project, executions=[ScriptedUnavailable()]))
    (event,) = _executions(project)
    assert (event.status, event.status_reason) == (EventStatus.ERROR, "executor_unavailable")
    assert event.data == {
        "execution_run_id": "r001",
        "image_digest": IMAGE,
        "exit_status": None,
        "stopped_by": None,
    }
    assert event.duration_ms is None
    assert event.output_hash is None
    assert event.input_hash == hash_file(project / "code" / "main.py")


def test_a_run_whose_image_is_not_the_recorded_one_is_refused_and_recorded(
    project: Path, tmp_path: Path
) -> None:
    image = tmp_path / "image"
    image.mkdir()
    (image / "digest.txt").write_text("sha256:" + "b" * 64 + "\n", encoding="utf-8")
    run_services = services(project, executions=[PASSED])
    run_services.image_directory = image
    with pytest.raises(ExecutorError, match="recorded"):
        run_workflow(project, run_services)
    (event,) = _executions(project)
    assert (event.status, event.status_reason) == (EventStatus.ERROR, "image_mismatch")
    assert not (project / "runs" / "r001").exists()


# utux validate


def test_validate_reports_a_manifest_without_its_code_execution_event(project: Path) -> None:
    run_workflow(project, services(project, executions=[PASSED]))
    copy = project / "runs" / "r002"
    shutil.copytree(project / "runs" / "r001", copy)
    manifest = json.loads((copy / "manifest.json").read_text("utf-8"))
    manifest["run_id"] = "r002"
    (copy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    problems = [(p.file, p.code) for p in validate_project(project).problems]
    assert ("runs/r002/manifest.json", "code_execution_missing") in problems


def test_validate_reports_a_manifest_with_two_code_execution_events(project: Path) -> None:
    run_workflow(project, services(project, executions=[PASSED]))
    EventLog(project / "events.jsonl").append(
        NewEvent(
            actor="system:utux",
            type=EventType.CODE_EXECUTION,
            status=EventStatus.OK,
            data={
                "execution_run_id": "r001",
                "image_digest": IMAGE,
                "exit_status": 0,
                "stopped_by": None,
            },
        )
    )
    problems = [(p.file, p.code) for p in validate_project(project).problems]
    assert problems == [("runs/r001/manifest.json", "code_execution_duplicate")]
