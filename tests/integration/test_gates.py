"""M1-11: approval gates and pauses.

The model and the executor are scripted, and the answers to approval
requests are written here as a person's CLI would write them (`utux approve`
is task M1-14). The ids such as `human:alex` are synthetic.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from workflow_scripts import CODE, METHOD, QUESTION, configure_models, services, switch_gates_off

from utux.core.workflow import mark_stale, resume_workflow, run_workflow
from utux.errors import ApprovalMismatchError, RunPausedError, RunRejectedError
from utux.events.log import EventLog
from utux.schemas.approval import ApprovalKind, load_approval_request
from utux.schemas.artifact_metadata import ArtifactState, load_artifact_metadata
from utux.schemas.event import Event, EventType
from utux.schemas.project_config import DataPolicy
from utux.workspace.hashing import hash_file
from utux.workspace.project import init_project
from utux.workspace.validation import validate_project

CHILD = Path(__file__).resolve().parent / "workflow_child.py"


@pytest.fixture
def git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return config


def make_project(path: Path, budget_usd: float = 5) -> Path:
    project = init_project(path, budget_usd=budget_usd, data_policy=DataPolicy.LOCAL_ONLY)
    (project / "inputs" / "question.md").write_text(QUESTION, encoding="utf-8")
    configure_models(project)
    return project


@pytest.fixture
def project(tmp_path: Path, git_config: Path) -> Path:
    # guided mode: both gates of stages 3 to 5 are on.
    return make_project(tmp_path / "p")


def _events(project: Path, kind: EventType | None = None) -> list[Event]:
    events = list(EventLog(project / "events.jsonl"))
    return events if kind is None else [e for e in events if e.type is kind]


def _edit_config(project: Path, old: str, new: str) -> None:
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    config.write_text(text.replace(old, new), encoding="utf-8")


def answer(project: Path, approval_id: str, decision: str, **fields: Any) -> None:
    """Write a person's answer to a request, as `utux approve` will."""
    request = load_approval_request(project / "approvals" / f"{approval_id}.request.json")
    response = {
        "schema_version": 1,
        "approval_id": approval_id,
        "kind": request.kind.value,
        "artifact_id": request.artifact_id,
        "content_hash": request.content_hash,
        "decision": decision,
        "answered_by": "human:alex",
        "answered_at": "2026-11-21T12:00:00Z",
        "feedback": "Synthetic feedback." if decision == "reject" else None,
        "edited_artifact_id": None,
        "edited_content_hash": None,
        **fields,
    }
    path = project / "approvals" / f"{approval_id}.response.json"
    path.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")


def _paused(project: Path, replies: tuple[str, ...] = (), **kwargs: Any) -> RunPausedError:
    start = kwargs.pop("start", False)
    action = run_workflow if start else resume_workflow
    with pytest.raises(RunPausedError) as caught:
        action(project, services(project, replies, **kwargs))
    return caught.value


# The gates


def test_guided_mode_pauses_after_methodology_for_the_method(project: Path) -> None:
    paused = _paused(project, (METHOD, CODE), start=True)
    assert paused.approval_id == "a-000001"
    assert "approvals/a-000001.request.json" in str(paused)
    request = load_approval_request(project / "approvals" / "a-000001.request.json")
    assert request.kind is ApprovalKind.ARTIFACT
    assert request.gate is not None
    assert request.gate.value == "method"
    assert (request.artifact_id, request.path) == ("method-v001", "method.md")
    assert request.content_hash == hash_file(project / "method.md")
    (requested,) = _events(project, EventType.APPROVAL_REQUESTED)
    assert requested.data == {"approval_id": "a-000001", "kind": "artifact", "gate": "method"}
    # Nothing of the implementation started, and the lock is released.
    nodes = [e.data["node"] for e in _events(project, EventType.STAGE_START)]
    assert nodes == ["methodology"]
    assert not (project / ".utux" / "lock").exists()
    assert validate_project(project).problems == ()


def test_resuming_before_an_answer_stays_paused_on_the_same_request(project: Path) -> None:
    _paused(project, (METHOD, CODE), start=True)
    again = _paused(project)
    assert again.approval_id == "a-000001"
    assert sorted(p.name for p in (project / "approvals").glob("*.json")) == [
        "a-000001.request.json"
    ]


def test_check_2_the_run_continues_from_each_gate_once_it_is_answered(project: Path) -> None:
    _paused(project, (METHOD, CODE), start=True)
    answer(project, "a-000001", "approve")
    paused = _paused(project, (CODE,))
    assert paused.approval_id == "a-000002"
    request = load_approval_request(project / "approvals" / "a-000002.request.json")
    assert request.gate is not None
    assert request.gate.value == "experiment_plan"
    assert (request.artifact_id, request.path) == ("code-v001", "code/main.py")
    answer(project, "a-000002", "approve")
    outcome = resume_workflow(project, services(project, ()))
    assert [r.id for r in outcome.results] == ["R0001"]
    answered = _events(project, EventType.APPROVAL_ANSWERED)
    assert [e.data for e in answered] == [
        {"approval_id": "a-000001", "decision": "approve"},
        {"approval_id": "a-000002", "decision": "approve"},
    ]
    assert validate_project(project).problems == ()


def test_check_2_across_processes(tmp_path: Path, git_config: Path) -> None:
    project = make_project(tmp_path / "p")
    environment = {**os.environ}

    def child(mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHILD), str(project), mode],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=300,
        )

    first = child("run")
    assert first.returncode != 0
    assert "a-000001" in first.stderr
    answer(project, "a-000001", "approve")
    second = child("resume-with-code")
    assert second.returncode != 0
    assert "a-000002" in second.stderr
    answer(project, "a-000002", "approve")
    third = child("resume")
    assert third.returncode == 0, third.stderr
    assert (project / "results.md").is_file()


def test_auto_mode_pauses_only_at_the_gates_switched_on(project: Path) -> None:
    _edit_config(project, "mode: guided", "mode: auto")
    _edit_config(project, "    method: null\n", "    method: true\n")
    _paused(project, (METHOD, CODE), start=True)
    answer(project, "a-000001", "approve")
    outcome = resume_workflow(project, services(project, (CODE,)))
    assert [r.id for r in outcome.results] == ["R0001"]
    assert len(_events(project, EventType.APPROVAL_REQUESTED)) == 1


def test_auto_mode_without_gates_does_not_pause(project: Path) -> None:
    _edit_config(project, "mode: guided", "mode: auto")
    run_workflow(project, services(project))
    assert _events(project, EventType.APPROVAL_REQUESTED) == []


def test_a_rejection_stops_the_run(project: Path) -> None:
    _paused(project, (METHOD, CODE), start=True)
    answer(project, "a-000001", "reject")
    with pytest.raises(RunRejectedError, match="a-000001"):
        resume_workflow(project, services(project, (CODE,)))
    (answered,) = _events(project, EventType.APPROVAL_ANSWERED)
    assert answered.data == {"approval_id": "a-000001", "decision": "reject"}
    nodes = [e.data["node"] for e in _events(project, EventType.STAGE_START)]
    assert nodes == ["methodology"]


# An edit


def _edit_method(project: Path) -> str:
    edited = METHOD + "\nEdited at the gate.\n"
    (project / "method.md").write_text(edited, encoding="utf-8")
    return hash_file(project / "method.md")


def test_an_edit_is_taken_as_a_new_version_by_the_person(project: Path) -> None:
    _paused(project, (METHOD, CODE), start=True)
    edited = _edit_method(project)
    answer(
        project,
        "a-000001",
        "edit",
        edited_artifact_id="method-v002",
        edited_content_hash=edited,
    )
    _paused(project, (CODE,))
    version = load_artifact_metadata(project / ".utux" / "meta" / "method-v002.json")
    assert version.created_by == "human:alex"
    assert version.input_artifacts == ("method-v001",)
    assert version.content_hash == edited
    # The implementation was built from the edited version.
    code = load_artifact_metadata(project / ".utux" / "meta" / "code-v001.json")
    assert code.input_artifacts == ("method-v002",)
    assert not (project / ".utux" / "meta" / "method-v003.json").exists()
    assert validate_project(project).problems == ()


def test_an_edit_whose_hash_differs_from_the_file_is_not_taken(project: Path) -> None:
    _paused(project, (METHOD, CODE), start=True)
    _edit_method(project)
    answer(
        project,
        "a-000001",
        "edit",
        edited_artifact_id="method-v002",
        edited_content_hash="sha256:" + "0" * 64,
    )
    with pytest.raises(ApprovalMismatchError, match=r"method\.md"):
        resume_workflow(project, services(project, (CODE,)))
    assert not (project / ".utux" / "meta" / "method-v002.json").exists()
    assert _events(project, EventType.APPROVAL_ANSWERED) == []


def test_outputs_built_from_an_old_version_are_marked_stale(project: Path) -> None:
    meta = project / ".utux" / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    for name, inputs in (("a-v001", []), ("b-v001", ["a-v001"]), ("c-v001", ["b-v001"])):
        (project / f"{name}.txt").write_text(name, encoding="utf-8")
        sidecar = {
            "artifact_id": name,
            "path": f"{name}.txt",
            "stage": "methodology",
            "schema_version": 1,
            "created_by": "system:utux",
            "created_at": "2026-11-21T10:00:00Z",
            "input_artifacts": inputs,
            "content_hash": hash_file(project / f"{name}.txt"),
            "state": "valid",
        }
        (meta / f"{name}.json").write_text(json.dumps(sidecar), encoding="utf-8")
    assert mark_stale(project, "a-v001") == ("b-v001", "c-v001")
    states = {
        n: load_artifact_metadata(meta / f"{n}.json").state for n in ("a-v001", "b-v001", "c-v001")
    }
    assert states == {
        "a-v001": ArtifactState.VALID,
        "b-v001": ArtifactState.STALE,
        "c-v001": ArtifactState.STALE,
    }


# Pauses for the budget


def test_an_exhausted_budget_pauses_with_the_refused_call(tmp_path: Path, git_config: Path) -> None:
    project = make_project(tmp_path / "p", budget_usd=0.001)
    switch_gates_off(project)
    # The methodology's call costs more than the budget, so the next is refused.
    paused = _paused(project, (METHOD, CODE), cost_usd=0.002, start=True)
    request = load_approval_request(project / "approvals" / f"{paused.approval_id}.request.json")
    assert request.kind is ApprovalKind.BUDGET_EXHAUSTED
    assert request.stage is not None
    assert request.stage.value == "implementation"
    refused = [e for e in _events(project, EventType.MODEL_CALL) if e.status.value == "refused"]
    assert request.refused_event_id == refused[-1].event_id
    assert validate_project(project).problems == ()


def test_approve_without_raising_the_budget_stays_paused(tmp_path: Path, git_config: Path) -> None:
    project = make_project(tmp_path / "p", budget_usd=0.001)
    switch_gates_off(project)
    paused = _paused(project, (METHOD, CODE), cost_usd=0.002, start=True)
    answer(project, paused.approval_id, "approve")
    again = _paused(project, (CODE,), cost_usd=0.002)
    assert again.approval_id == paused.approval_id
    assert "budget" in str(again)
    assert [e.data["node"] for e in _events(project, EventType.STAGE_END)] == ["methodology"]


def test_raising_the_budget_and_approving_repeats_the_refused_call(
    tmp_path: Path, git_config: Path
) -> None:
    project = make_project(tmp_path / "p", budget_usd=0.001)
    switch_gates_off(project)
    paused = _paused(project, (METHOD, CODE), cost_usd=0.002, start=True)
    answer(project, paused.approval_id, "approve")
    _edit_config(project, "total_usd: 0.001", "total_usd: 1.0")
    outcome = resume_workflow(project, services(project, (CODE,), cost_usd=0.002))
    assert [r.id for r in outcome.results] == ["R0001"]
    calls = _events(project, EventType.MODEL_CALL)
    # methodology ok, implementation refused, then implementation again, ok.
    assert [(e.stage.value if e.stage else None, e.status.value) for e in calls] == [
        ("methodology", "ok"),
        ("implementation", "refused"),
        ("implementation", "ok"),
    ]
    changes = [
        e
        for e in _events(project, EventType.SETTING_CHANGED)
        if e.data["key"] == "budget.total_usd"
    ]
    requested = _events(project, EventType.APPROVAL_REQUESTED)[-1]
    assert changes
    assert int(changes[-1].event_id[2:]) > int(requested.event_id[2:])


def test_rejecting_a_budget_pause_stops_the_run(tmp_path: Path, git_config: Path) -> None:
    project = make_project(tmp_path / "p", budget_usd=0.001)
    switch_gates_off(project)
    paused = _paused(project, (METHOD, CODE), cost_usd=0.002, start=True)
    answer(project, paused.approval_id, "reject")
    with pytest.raises(RunRejectedError):
        resume_workflow(project, services(project, (CODE,), cost_usd=0.002))
