"""M1-14: `utux run`, `utux approve`, `utux status` and `utux unlock`.

The model and the executor are scripted (`workflow_scripts`); the CLI is
given them in place of the real services. Nothing is executed. The person
`human:alex` is synthetic.
"""

import importlib
import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner
from workflow_scripts import (
    CODE,
    IMAGE,
    METHOD,
    METHOD_MD,
    QUESTION,
    Raw,
    Reply,
    configure_models,
    services,
    switch_gates_off,
)

from utux.cli import app
from utux.core.workflow import WorkflowServices, current_artifact, planned_execution
from utux.events.log import EventLog
from utux.executors.scripted import ScriptedRun
from utux.schemas.approval import load_approval_request, load_approval_response
from utux.schemas.event import Event, EventStatus, EventType, NewEvent
from utux.schemas.project_config import DataPolicy, load_project_config
from utux.workspace.hashing import hash_file
from utux.workspace.project import init_project

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
# The module, not the Typer object that utux.cli re-exports under the same name.
cli = importlib.import_module("utux.cli.app")


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
    return project


def _script(
    monkeypatch: pytest.MonkeyPatch,
    replies: Sequence[Reply] = (METHOD, CODE),
    executions: Sequence[ScriptedRun] | None = None,
) -> list[WorkflowServices]:
    """Give every later `utux run` fresh scripted services; return them as they are made."""
    made: list[WorkflowServices] = []

    def factory(project: Path) -> WorkflowServices:
        made.append(services(project, replies, executions=executions))
        return made[-1]

    monkeypatch.setattr(cli, "services_for_run", factory)
    return made


def _utux(*arguments: str) -> tuple[int, str]:
    result = runner.invoke(app, list(arguments))
    return result.exit_code, result.output


def _events(project: Path, kind: EventType | None = None) -> list[Event]:
    return [e for e in EventLog(project / "events.jsonl") if kind is None or e.type is kind]


def _nodes(project: Path) -> list[str]:
    return [str(e.data["node"]) for e in _events(project, EventType.STAGE_START)]


def _approve(project: Path, *arguments: str) -> tuple[int, str]:
    return _utux("approve", str(project), *arguments, "--by", "alex")


# utux run


def test_run_starts_a_run_and_reports_that_it_finished(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch_gates_off(project)
    _script(monkeypatch)
    code, output = _utux("run", str(project))
    assert code == 0, output
    (started,) = _events(project, EventType.RUN_STARTED)
    assert f"Run {started.event_id} finished" in output
    assert "1 result record" in output
    assert _nodes(project) == ["methodology", "implementation", "experiment", "analysis"]


def test_run_pauses_at_a_gate_and_says_how_to_answer(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    code, output = _utux("run", str(project))
    # Exit status 3: paused for an approval (PR #38 review).
    assert code == 3, output
    assert "a-000001" in output
    assert f"utux approve {project} a-000001 approve|reject|edit" in output


def test_check_2_through_the_cli_run_approve_run_approve_run(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    assert _utux("run", str(project))[0] == 3
    assert _approve(project, "a-000001", "approve")[0] == 0
    code, output = _utux("run", str(project))
    assert code == 3, output
    assert "a-000002" in output
    assert _approve(project, "a-000002", "approve")[0] == 0
    code, output = _utux("run", str(project))
    assert code == 0, output
    assert "finished" in output
    assert len(_events(project, EventType.RUN_STARTED)) == 1
    assert _nodes(project) == ["methodology", "implementation", "experiment", "analysis"]


def test_run_to_a_stage_stops_after_it_and_a_later_run_continues(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch_gates_off(project)
    _script(monkeypatch)
    code, output = _utux("run", str(project), "--to", "methodology")
    assert code == 0, output
    assert "stopped after methodology" in output
    assert _nodes(project) == ["methodology"]
    code, output = _utux("run", str(project))
    assert code == 0, output
    assert "finished" in output
    assert _nodes(project) == ["methodology", "implementation", "experiment", "analysis"]
    assert len(_events(project, EventType.RUN_STARTED)) == 1


def test_run_to_a_stage_the_run_is_already_past_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch_gates_off(project)
    _script(monkeypatch)
    assert _utux("run", str(project), "--to", "implementation")[0] == 0
    before = (project / "events.jsonl").read_bytes()
    code, output = _utux("run", str(project), "--to", "methodology")
    assert code == 1
    assert "methodology" in output
    assert "experiment" in output
    assert (project / "events.jsonl").read_bytes() == before


def test_run_from_a_stage_starts_a_new_run_there(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch_gates_off(project)
    _script(monkeypatch, (METHOD, CODE))
    assert _utux("run", str(project))[0] == 0
    made = _script(monkeypatch, (CODE,))
    code, output = _utux("run", str(project), "--from", "implementation")
    assert code == 0, output
    first, second = _events(project, EventType.RUN_STARTED)
    later = [
        str(e.data["node"])
        for e in _events(project, EventType.STAGE_START)
        if e.run_id == second.event_id
    ]
    assert later == ["implementation", "experiment", "analysis"]
    assert f"Run {second.event_id} finished" in output
    (request,) = made[0].provider.of("implementer")  # type: ignore[attr-defined]
    assert METHOD_MD in request.messages[-1].content
    assert first.event_id != second.event_id


def test_run_from_a_stage_records_a_hand_edit_of_its_input_first(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch_gates_off(project)
    _script(monkeypatch, (METHOD, CODE))
    assert _utux("run", str(project))[0] == 0
    edited = METHOD_MD + "\nEdited by hand.\n"
    (project / "method.md").write_text(edited, encoding="utf-8")
    made = _script(monkeypatch, (CODE,))
    code, output = _utux("run", str(project), "--from", "implementation")
    assert code == 0, output
    current = current_artifact(project, "method.md")
    assert current is not None
    assert (current.artifact_id, current.created_by) == ("method-v002", "human:unknown")
    (request,) = made[0].provider.of("implementer")  # type: ignore[attr-defined]
    assert "Edited by hand." in request.messages[-1].content


def test_run_from_a_stage_without_its_input_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch, (CODE,))
    before = (project / "events.jsonl").read_bytes()
    code, output = _utux("run", str(project), "--from", "implementation")
    assert code == 1
    assert "method.md" in output
    assert (project / "events.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    ("arguments", "words"),
    [
        (("--from", "ideation"), ("ideation", "methodology, implementation and experiment")),
        (("--to", "writing"), ("writing", "methodology, implementation and experiment")),
        (("--from", "experiment", "--to", "implementation"), ("implementation", "experiment")),
    ],
)
def test_run_refuses_stages_it_cannot_run(
    project: Path, monkeypatch: pytest.MonkeyPatch, arguments: tuple[str, ...], words: tuple[str]
) -> None:
    _script(monkeypatch)
    before = (project / "events.jsonl").read_bytes()
    code, output = _utux("run", str(project), *arguments)
    assert code != 0
    for word in words:
        assert word in output
    assert (project / "events.jsonl").read_bytes() == before


# utux approve


def test_approve_writes_a_response_for_the_exact_version(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    code, output = _approve(project, "a-000001", "approve")
    assert code == 0, output
    request = load_approval_request(project / "approvals" / "a-000001.request.json")
    response = load_approval_response(project / "approvals" / "a-000001.response.json")
    assert response.decision.value == "approve"
    assert response.answered_by == "human:alex"
    assert (response.artifact_id, response.content_hash) == (
        request.artifact_id,
        request.content_hash,
    )
    assert response.feedback is None
    assert response.answered_at.endswith("Z")


def test_approve_takes_the_person_from_the_login_name_by_default(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    for name in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LOGNAME", "alex")
    code, output = _utux("approve", str(project), "a-000001", "approve")
    assert code == 0, output
    response = load_approval_response(project / "approvals" / "a-000001.response.json")
    assert response.answered_by == "human:alex"


@pytest.mark.parametrize("person", ["unknown", "Alex Smith", ""])
def test_approve_refuses_a_person_id_it_cannot_record(
    project: Path, monkeypatch: pytest.MonkeyPatch, person: str
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    code, output = _utux("approve", str(project), "a-000001", "approve", "--by", person)
    assert code == 1
    assert "--by" in output
    assert not (project / "approvals" / "a-000001.response.json").exists()


def test_reject_needs_feedback_and_records_it(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    code, output = _approve(project, "a-000001", "reject")
    assert code == 1
    assert "--feedback" in output
    assert not (project / "approvals" / "a-000001.response.json").exists()
    code, output = _approve(project, "a-000001", "reject", "--feedback", "Synthetic feedback.")
    assert code == 0, output
    response = load_approval_response(project / "approvals" / "a-000001.response.json")
    assert response.feedback == "Synthetic feedback."


def test_edit_records_the_saved_file_as_a_new_version_by_the_person(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch, (METHOD, CODE))
    _utux("run", str(project))
    edited = METHOD_MD + "\nEdited at the gate.\n"
    (project / "method.md").write_text(edited, encoding="utf-8")
    code, output = _approve(project, "a-000001", "edit")
    assert code == 0, output
    assert "method-v002" in output
    response = load_approval_response(project / "approvals" / "a-000001.response.json")
    assert response.edited_artifact_id == "method-v002"
    assert response.edited_content_hash == hash_file(project / "method.md")
    # The run takes the edit when it resumes and records the version as the person's.
    _utux("run", str(project))
    current = current_artifact(project, "method.md")
    assert current is not None
    assert (current.artifact_id, current.created_by) == ("method-v002", "human:alex")


def test_edit_of_an_unchanged_file_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    code, output = _approve(project, "a-000001", "edit")
    assert code == 1
    assert "approve" in output
    assert not (project / "approvals" / "a-000001.response.json").exists()


def test_approving_a_file_that_changed_since_the_request_is_refused(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    (project / "method.md").write_text(METHOD_MD + "\nChanged.\n", encoding="utf-8")
    code, output = _approve(project, "a-000001", "approve")
    assert code == 1
    assert "edit" in output
    assert not (project / "approvals" / "a-000001.response.json").exists()


def test_a_request_is_answered_once(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    assert _approve(project, "a-000001", "approve")[0] == 0
    first = (project / "approvals" / "a-000001.response.json").read_bytes()
    code, output = _approve(project, "a-000001", "reject", "--feedback", "Too late.")
    assert code == 1
    assert "already answered" in output
    assert (project / "approvals" / "a-000001.response.json").read_bytes() == first


def test_approve_refuses_an_unknown_request(project: Path) -> None:
    code, output = _approve(project, "a-000009", "approve")
    assert code == 1
    assert "a-000009" in output


def test_approve_waits_for_the_project_lock(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    _write_lock(project, os.getpid(), socket.gethostname(), "run")
    code, output = _approve(project, "a-000001", "approve")
    assert code == 1
    assert "locked" in output
    assert not (project / "approvals" / "a-000001.response.json").exists()


# utux status


def _write_lock(project: Path, pid: int, host: str, command: str) -> None:
    holder = {"pid": pid, "host": host, "command": command, "started_at": "2026-11-21T09:00:00Z"}
    (project / ".utux" / "lock").write_text(json.dumps(holder) + "\n", encoding="utf-8")


def _dead_pid() -> int:
    """The id of a process that has ended (and been reaped)."""
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    return process.pid


def test_status_of_a_project_without_a_run(project: Path) -> None:
    code, output = _utux("status", str(project))
    assert code == 0, output
    assert "No run yet" in output
    assert "0 USD of a budget of 5 USD" in output
    assert "Lock: not held" in output


def test_status_shows_the_paused_stage_and_the_execution_beside_an_experiment_plan_request(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    _approve(project, "a-000001", "approve")
    _utux("run", str(project))
    before = (project / "events.jsonl").read_bytes()
    code, output = _utux("status", str(project))
    assert code == 0, output
    assert "paused at a-000002" in output
    assert "Stage: implementation" in output
    assert "a-000002" in output
    assert "experiment_plan" in output
    planned = planned_execution(load_project_config(project / "utux.yaml"), IMAGE)
    assert f"command: {' '.join(planned.command)}" in output
    assert f"image: {IMAGE}" in output
    assert f"read-only paths: {', '.join(planned.read_only_paths)}" in output
    assert f"timeout {planned.limits.timeout_seconds:g} s" in output
    # The limits are those that apply: the executor's defaults where utux.yaml sets none.
    assert "not set" not in output
    assert "cpus 1, memory 2048 MB, gpus 0, disk 512 MB, processes 256, output 1024 MB" in output
    # status is read-only.
    assert (project / "events.jsonl").read_bytes() == before


def test_status_of_a_finished_run(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_gates_off(project)
    _script(monkeypatch)
    _utux("run", str(project))
    code, output = _utux("status", str(project))
    assert code == 0, output
    assert "finished" in output
    assert "Pending approvals: none" in output


def test_status_notes_that_exit_status_137_is_often_the_memory_limit(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch_gates_off(project)
    killed = ScriptedRun(exit_status=137, stderr=b"synthetic: killed\n")
    _script(monkeypatch, (METHOD, CODE, CODE, CODE), [killed, killed, killed])
    _utux("run", str(project))
    code, output = _utux("status", str(project))
    assert code == 0, output
    assert "exit status 137" in output
    assert "often the memory limit" in output
    assert "retry_limit" in output
    # The note is only shown; the run's record names no limit.
    manifest = json.loads((project / "runs" / "r003" / "manifest.json").read_text("utf-8"))
    assert (manifest["exit_status"], manifest["stopped_by"]) == (137, None)


@pytest.mark.parametrize(
    ("holder", "words"),
    [
        (lambda: (os.getpid(), socket.gethostname(), "run"), ("held by the run",)),
        (lambda: (os.getpid(), socket.gethostname(), "model ping"), ("model ping",)),
        (lambda: (_dead_pid(), socket.gethostname(), "run"), ("no longer running", "utux unlock")),
        (lambda: (1, "synthetic-other-host", "run"), ("synthetic-other-host", "cannot be checked")),
    ],
)
def test_status_says_who_holds_the_lock(
    project: Path, holder: Callable[[], tuple[int, str, str]], words: tuple[str, ...]
) -> None:
    _write_lock(project, *holder())
    code, output = _utux("status", str(project))
    assert code == 0, output
    for word in words:
        assert word in output


# utux unlock


def test_unlock_removes_a_lock_left_by_a_process_that_is_gone(project: Path) -> None:
    pid = _dead_pid()
    _write_lock(project, pid, socket.gethostname(), "run")
    code, output = _utux("unlock", str(project))
    assert code == 0, output
    assert not (project / ".utux" / "lock").exists()
    (removed,) = _events(project, EventType.LOCK_REMOVED)
    assert removed.data == {
        "pid": pid,
        "host": socket.gethostname(),
        "command": "run",
        "started_at": "2026-11-21T09:00:00Z",
    }
    assert removed.event_id in output


def test_unlock_refuses_a_lock_whose_process_is_running(project: Path) -> None:
    _write_lock(project, os.getpid(), socket.gethostname(), "run")
    code, output = _utux("unlock", str(project))
    assert code == 1
    assert "still running" in output
    assert (project / ".utux" / "lock").exists()
    assert _events(project, EventType.LOCK_REMOVED) == []


def test_unlock_refuses_a_lock_of_another_host(project: Path) -> None:
    _write_lock(project, 1, "synthetic-other-host", "run")
    code, output = _utux("unlock", str(project))
    assert code == 1
    assert "synthetic-other-host" in output
    assert (project / ".utux" / "lock").exists()


def test_unlock_refuses_a_lock_it_cannot_read(project: Path) -> None:
    (project / ".utux" / "lock").write_text("not json\n", encoding="utf-8")
    code, output = _utux("unlock", str(project))
    assert code == 1
    assert "cannot be read" in output
    assert (project / ".utux" / "lock").exists()


def test_unlock_without_a_lock_says_so(project: Path) -> None:
    code, output = _utux("unlock", str(project))
    assert code == 1
    assert "not locked" in output


# Every command refuses a project that fails utux validate


@pytest.mark.parametrize(
    "arguments",
    [
        ("run",),
        ("approve", "a-000001", "approve", "--by", "alex"),
        ("status",),
        ("unlock",),
    ],
)
def test_every_run_command_refuses_a_project_that_fails_validate(
    project: Path, monkeypatch: pytest.MonkeyPatch, arguments: tuple[str, ...]
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    _write_lock(project, _dead_pid(), socket.gethostname(), "run")
    with (project / "events.jsonl").open("ab") as log:
        log.write(b'{"synthetic": "not an event"}\n')
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    command, *rest = arguments
    code, output = _utux(command, str(project), *rest)
    assert code == 1
    assert "utux validate" in output
    assert {p: p.read_bytes() for p in project.rglob("*") if p.is_file()} == before


def test_a_file_edited_since_its_version_is_acted_on_and_validate_still_reports_it(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The edit is what utux run (files win) and utux approve edit record; the
    # run commands do not refuse it, but utux validate reports it as before.
    _script(monkeypatch)
    _utux("run", str(project))
    (project / "method.md").write_text(METHOD_MD + "\nEdited.\n", encoding="utf-8")
    code, output = _utux("validate", str(project))
    assert code == 1
    assert "content_hash" in output or "the file changed" in output
    code, output = _utux("status", str(project))
    assert code == 0, output
    code, output = _approve(project, "a-000001", "edit")
    assert code == 0, output


# Exit status of utux run (PR #38 review): 0 completed, 1 error, 3 paused


def test_run_exits_0_when_the_run_completes(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    switch_gates_off(project)
    _script(monkeypatch)
    assert _utux("run", str(project))[0] == 0


def test_run_exits_1_on_an_error(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _script(monkeypatch)
    code, output = _utux("run", str(project), "--from", "implementation")
    assert code == 1
    assert output.startswith("error:")


def test_run_exits_3_when_it_pauses_for_an_approval(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    code, output = _utux("run", str(project))
    assert code == 3
    assert "Run paused" in output


# The id utux approve records (PR #38 review)


def test_approve_prints_the_person_id_it_recorded(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    code, output = _approve(project, "a-000001", "approve")
    assert code == 0, output
    assert "Recorded you as human:alex" in output
    assert "--by" in output


# Recovery after a crash through utux log repair (PR #38 review)


def _cut_last_line(project: Path) -> None:
    log = project / "events.jsonl"
    log.write_bytes(log.read_bytes() + b'{"schema_version": 1, "event_id": "e-0')


def test_one_log_repair_recovers_a_stale_lock_and_an_incomplete_last_line(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script(monkeypatch)
    _utux("run", str(project))
    pid = _dead_pid()
    _write_lock(project, pid, socket.gethostname(), "run")
    _cut_last_line(project)
    code, output = _utux("log", "repair", str(project))
    assert code == 0, output
    assert not (project / ".utux" / "lock").exists()
    *_, removed, repaired = _events(project)
    assert removed.type is EventType.LOCK_REMOVED
    assert removed.data == {
        "pid": pid,
        "host": socket.gethostname(),
        "command": "run",
        "started_at": "2026-11-21T09:00:00Z",
    }
    assert repaired.type is EventType.LOG_REPAIRED
    assert removed.event_id in output
    assert _utux("validate", str(project))[0] == 0
    # The project is usable again.
    assert _utux("status", str(project))[0] == 0


def test_log_repair_removes_a_stale_lock_when_the_log_is_complete(project: Path) -> None:
    _write_lock(project, _dead_pid(), socket.gethostname(), "run")
    code, output = _utux("log", "repair", str(project))
    assert code == 0, output
    assert not (project / ".utux" / "lock").exists()
    # The fixture edited utux.yaml, so setting changes are recorded after it.
    kinds = [e.type for e in _events(project)]
    assert kinds.count(EventType.LOCK_REMOVED) == 1
    assert EventType.LOG_REPAIRED not in kinds


@pytest.mark.parametrize(
    "holder",
    [
        lambda: (os.getpid(), socket.gethostname(), "run"),
        lambda: (1, "synthetic-other-host", "run"),
    ],
)
def test_log_repair_refuses_a_lock_that_is_held_or_cannot_be_checked(
    project: Path, holder: Callable[[], tuple[int, str, str]]
) -> None:
    _write_lock(project, *holder())
    _cut_last_line(project)
    before = (project / "events.jsonl").read_bytes()
    code, output = _utux("log", "repair", str(project))
    assert code == 1
    assert "locked" in output
    assert (project / ".utux" / "lock").exists()
    assert (project / "events.jsonl").read_bytes() == before


def test_status_shows_the_trace_beside_the_error(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    switch_gates_off(project)
    _script(monkeypatch, (Raw("methodologist", "not json"), Raw("methodologist", "not json")))
    assert _utux("run", str(project))[0] == 1
    code, output = _utux("status", str(project))
    assert code == 0, output
    calls = _events(project, EventType.MODEL_CALL)
    assert f"invalid_structured_output; trace .utux/traces/{calls[-1].event_id}.txt" in output


def test_a_project_from_before_traces_continues_with_utux_run(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As the maintainer's first M1-16 project: methodology failed twice, and
    # the error event, written before the trace key, has empty data.
    switch_gates_off(project)
    _script(monkeypatch, (Raw("methodologist", "not json"), Raw("methodologist", "not json")))
    assert _utux("run", str(project))[0] == 1
    (run,) = _events(project, EventType.RUN_STARTED)
    EventLog(project / "events.jsonl").append(
        NewEvent(
            actor="system:utux",
            type=EventType.ERROR,
            status=EventStatus.ERROR,
            status_reason="invalid_structured_output",
            run_id=run.event_id,
            data={},
        )
    )
    assert _utux("validate", str(project))[0] == 0
    _script(monkeypatch)
    code, output = _utux("run", str(project))
    assert code == 0, output
    assert "finished" in output
