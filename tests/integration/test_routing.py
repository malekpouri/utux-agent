"""M1-12: routing back to an earlier stage, and the retry cap.

Two deterministic checks run after the analysis, as a stand-in for a
reviewer: the run's exit status is zero, and every metric `method.md` names
has a result record. The model and executor are scripted; nothing runs.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from workflow_scripts import (
    CODE,
    IMAGE,
    METHOD,
    METRICS,
    QUESTION,
    configure_models,
    switch_gates_off,
)

from utux.core.workflow import RETRY_CAP, WorkflowServices, resume_workflow, run_workflow
from utux.errors import RunPausedError, RunRejectedError
from utux.events.log import EventLog
from utux.executors.scripted import ScriptedExecutor, ScriptedRun
from utux.providers.scripted import ScriptedModelProvider, ScriptedReply
from utux.schemas.approval import ApprovalKind, load_approval_request
from utux.schemas.event import Event, EventStatus, EventType
from utux.schemas.project_config import DataPolicy
from utux.workspace.project import init_project
from utux.workspace.validation import validate_project

METHOD_NAMING_ACCURACY = (
    "# Method\n\nSynthetic method.\n\n## Success criteria\n\n- metric: accuracy\n"
)
METHOD_NAMING_R2 = (
    "# Method\n\nSynthetic method, second version.\n\n## Success criteria\n\n- metric: r2\n"
)
CODE_FIXED = "print('synthetic experiment, fixed')\n"

FAILED = ScriptedRun(exit_status=1, stderr=b"synthetic failure\n")
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
    return project


def _services(
    project: Path, replies: tuple[str, ...], runs: list[ScriptedRun]
) -> tuple[WorkflowServices, ScriptedModelProvider]:
    provider = ScriptedModelProvider(
        [ScriptedReply(content=reply, cost_usd=0.0) for reply in replies],
        name="scripted",
        is_external=False,
    )
    services = WorkflowServices(
        provider=provider,
        executor=ScriptedExecutor(project, runs),
        image_digest=IMAGE,
        locked_packages=lambda digest: {"numpy": "2.5.5"},
        rootless=False,
    )
    return services, provider


def _events(project: Path, kind: EventType) -> list[Event]:
    return [e for e in EventLog(project / "events.jsonl") if e.type is kind]


def _answer(project: Path, approval_id: str, decision: str) -> None:
    request = load_approval_request(project / "approvals" / f"{approval_id}.request.json")
    response: dict[str, Any] = {
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
    }
    (project / "approvals" / f"{approval_id}.response.json").write_text(
        json.dumps(response), encoding="utf-8"
    )


def test_a_passing_run_is_not_routed_back(project: Path) -> None:
    switch_gates_off(project)
    services, _ = _services(project, (METHOD, CODE), [PASSED])
    run_workflow(project, services)
    assert _events(project, EventType.ROUTE_BACK) == []


def test_a_failed_run_routes_back_to_implementation_with_the_finding(project: Path) -> None:
    switch_gates_off(project)
    services, provider = _services(project, (METHOD, CODE, CODE_FIXED), [FAILED, PASSED])
    outcome = run_workflow(project, services)
    (route,) = _events(project, EventType.ROUTE_BACK)
    assert route.status is EventStatus.OK
    assert route.run_id == outcome.run_id
    assert route.data == {
        "from_stage": "experiment",
        "to_stage": "implementation",
        "finding": "run_failed",
        "attempt": 1,
        "cap": RETRY_CAP,
    }
    # The finding is passed to the stage as input.
    assert "run_failed" in provider.requests[2].messages[-1].content
    assert (project / "code" / "main.py").read_text(encoding="utf-8") == CODE_FIXED
    assert [r.run_id for r in outcome.results] == ["r002"]
    assert validate_project(project).problems == ()


def test_a_missing_metric_routes_back_to_methodology(project: Path) -> None:
    switch_gates_off(project)
    replies = (METHOD_NAMING_ACCURACY, CODE, METHOD_NAMING_R2, CODE)
    services, provider = _services(project, replies, [PASSED, PASSED])
    outcome = run_workflow(project, services)
    (route,) = _events(project, EventType.ROUTE_BACK)
    assert (route.data["to_stage"], route.data["finding"]) == ("methodology", "metric_missing")
    assert "metric_missing" in provider.requests[2].messages[-1].content
    assert (project / "method.md").read_text(encoding="utf-8") == METHOD_NAMING_R2
    assert [r.metric for r in outcome.results] == ["r2"]


def test_check_3_the_retry_cap_stops_the_loop_and_pauses(project: Path) -> None:
    switch_gates_off(project)
    replies = (METHOD,) + (CODE,) * (RETRY_CAP + 1)
    services, _ = _services(project, replies, [FAILED] * (RETRY_CAP + 1))
    with pytest.raises(RunPausedError) as caught:
        run_workflow(project, services)
    routes = _events(project, EventType.ROUTE_BACK)
    assert [(e.status, e.data["attempt"]) for e in routes] == [
        *[(EventStatus.OK, n) for n in range(1, RETRY_CAP + 1)],
        (EventStatus.REFUSED, RETRY_CAP + 1),
    ]
    refused = routes[-1]
    assert refused.status_reason == "retry_limit"
    request = load_approval_request(
        project / "approvals" / f"{caught.value.approval_id}.request.json"
    )
    assert request.kind is ApprovalKind.RETRY_LIMIT
    assert request.refused_event_id == refused.event_id
    assert request.stage is not None
    assert request.stage.value == "experiment"
    assert validate_project(project).problems == ()


def test_approving_the_retry_limit_allows_one_more_route_back(project: Path) -> None:
    switch_gates_off(project)
    replies = (METHOD,) + (CODE,) * (RETRY_CAP + 1)
    services, _ = _services(project, replies, [FAILED] * (RETRY_CAP + 1))
    with pytest.raises(RunPausedError) as caught:
        run_workflow(project, services)
    _answer(project, caught.value.approval_id, "approve")
    services, _ = _services(project, (CODE_FIXED,), [PASSED])
    outcome = resume_workflow(project, services)
    resumed = _events(project, EventType.ROUTE_BACK)[-1]
    assert resumed.status is EventStatus.OK
    assert (resumed.data["attempt"], resumed.data["cap"]) == (RETRY_CAP + 1, RETRY_CAP + 1)
    assert outcome.results


def test_rejecting_the_retry_limit_stops_the_run(project: Path) -> None:
    switch_gates_off(project)
    replies = (METHOD,) + (CODE,) * (RETRY_CAP + 1)
    services, _ = _services(project, replies, [FAILED] * (RETRY_CAP + 1))
    with pytest.raises(RunPausedError) as caught:
        run_workflow(project, services)
    _answer(project, caught.value.approval_id, "reject")
    services, _ = _services(project, (), [])
    with pytest.raises(RunRejectedError):
        resume_workflow(project, services)


# The experiment-plan approval and later setting changes (M1-11 review)


def _edit_config(project: Path, old: str, new: str) -> None:
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    config.write_text(text.replace(old, new), encoding="utf-8")


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("  memory_mb: null\n", "  memory_mb: 1024\n"),
        ("domain_pack: generic\n", "domain_pack: other\n"),
    ],
)
def test_a_change_of_resources_or_pack_after_the_plan_was_approved_asks_again(
    project: Path, old: str, new: str
) -> None:
    _edit_config(project, "    method: null\n", "    method: false\n")
    services, _ = _services(project, (METHOD, CODE), [PASSED])
    with pytest.raises(RunPausedError) as first:
        run_workflow(project, services)
    _answer(project, first.value.approval_id, "approve")
    _edit_config(project, old, new)
    services, _ = _services(project, (), [PASSED])
    with pytest.raises(RunPausedError) as second:
        resume_workflow(project, services)
    assert second.value.approval_id != first.value.approval_id
    request = load_approval_request(
        project / "approvals" / f"{second.value.approval_id}.request.json"
    )
    assert request.gate is not None
    assert request.gate.value == "experiment_plan"
    # Nothing ran yet.
    assert not (project / "runs" / "r001").exists()
    _answer(project, second.value.approval_id, "approve")
    services, _ = _services(project, (), [PASSED])
    assert resume_workflow(project, services).results


def test_a_change_of_another_setting_keeps_the_approval(project: Path) -> None:
    _edit_config(project, "    method: null\n", "    method: false\n")
    services, _ = _services(project, (METHOD, CODE), [PASSED])
    with pytest.raises(RunPausedError) as first:
        run_workflow(project, services)
    _answer(project, first.value.approval_id, "approve")
    _edit_config(project, "  draft: true\n", "  draft: false\n")
    services, _ = _services(project, (), [PASSED])
    assert resume_workflow(project, services).results
