"""M1-13: the three roles in a run: prompts, tiers, structured output and retry,
the analyst's numbers, and a rejection with feedback.

The model is scripted by role (workflow_scripts.RoleScriptedProvider); nothing
is executed. The person `human:alex` is synthetic.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from workflow_scripts import (
    CODE,
    METHOD,
    METHOD_MD,
    QUESTION,
    Raw,
    RoleScriptedProvider,
    configure_models,
    plan,
    rendered,
    services,
    switch_gates_off,
)

from utux.core.workflow import resume_workflow, run_workflow
from utux.errors import AgentOutputError, RunPausedError
from utux.events.log import EventLog
from utux.schemas.approval import ApprovalKind, load_approval_request
from utux.schemas.event import Event, EventStatus, EventType
from utux.schemas.project_config import DataPolicy
from utux.workspace.project import init_project
from utux.workspace.validation import validate_project


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
    (project / "inputs" / "data.md").write_text("Synthetic data: 100 points.\n", "utf-8")
    configure_models(project)
    return project


def _events(project: Path, kind: EventType) -> list[Event]:
    return [e for e in EventLog(project / "events.jsonl") if e.type is kind]


def _provider(run_services: Any) -> RoleScriptedProvider:
    provider = run_services.provider
    assert isinstance(provider, RoleScriptedProvider)
    return provider


def _edit_config(project: Path, old: str, new: str) -> None:
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    config.write_text(text.replace(old, new), encoding="utf-8")


# Prompts and tiers


def test_every_model_call_logs_its_prompt_version(project: Path) -> None:
    switch_gates_off(project)
    run_workflow(project, services(project))
    calls = _events(project, EventType.MODEL_CALL)
    assert [e.prompt_version for e in calls] == [
        "methodologist@3",
        "implementer@3",
        "analyst@5",
    ]


def test_the_methodologist_reads_the_inputs_and_writes_numbered_steps(project: Path) -> None:
    switch_gates_off(project)
    run_services = services(project)
    run_workflow(project, run_services)
    (request,) = _provider(run_services).of("methodologist")
    assert QUESTION.strip() in request.messages[-1].content
    assert "100 points" in request.messages[-1].content
    assert (project / "method.md").read_text(encoding="utf-8") == METHOD_MD


def test_each_role_uses_its_configured_tier(project: Path) -> None:
    switch_gates_off(project)
    _edit_config(
        project,
        "  tiers:\n    standard: scripted/standard-model\n",
        "  tiers:\n    standard: scripted/standard-model\n    strong: scripted/strong-model\n",
    )
    _edit_config(project, "  roles: {}\n", "  roles:\n    methodologist: strong\n")
    run_workflow(project, services(project))
    models = [e.model for e in _events(project, EventType.MODEL_CALL)]
    assert models == ["scripted/strong-model", "scripted/standard-model", "scripted/standard-model"]
    assert all(e.escalated_from is None for e in _events(project, EventType.MODEL_CALL))


def test_the_code_is_told_where_to_write_its_metrics(project: Path) -> None:
    switch_gates_off(project)
    run_services = services(project)
    run_workflow(project, run_services)
    (step,) = run_services.executor.steps  # type: ignore[attr-defined]
    assert step.environment == {"UTUX_OUTPUT_DIR": step.output_directory}
    (request,) = _provider(run_services).of("implementer")
    assert "UTUX_OUTPUT_DIR" in request.messages[0].content


# Structured output: JSON, validated, retried once


def test_an_invalid_reply_is_retried_once_with_its_problems(project: Path) -> None:
    switch_gates_off(project)
    run_services = services(project, (Raw("methodologist", "not json"), METHOD, CODE))
    run_workflow(project, run_services)
    _, second = _provider(run_services).of("methodologist")
    assert "not valid" in second.messages[-1].content
    calls = [
        e
        for e in _events(project, EventType.MODEL_CALL)
        if e.stage and e.stage.value == "methodology"
    ]
    assert [e.retry_reason for e in calls] == [None, "invalid_structured_output"]
    assert (project / "method.md").read_text(encoding="utf-8") == METHOD_MD


def test_a_second_invalid_reply_fails_the_stage_and_writes_nothing(project: Path) -> None:
    switch_gates_off(project)
    bad = Raw("methodologist", json.dumps({"steps": []}))
    with pytest.raises(AgentOutputError, match="methodologist"):
        run_workflow(project, services(project, (bad, bad)))
    (error,) = _events(project, EventType.ERROR)
    assert (error.status, error.status_reason) == (EventStatus.ERROR, "invalid_structured_output")
    assert error.stage is not None
    assert error.stage.value == "methodology"
    assert not (project / "method.md").exists()


def test_an_analysis_with_a_bare_number_is_retried_and_then_refused(project: Path) -> None:
    switch_gates_off(project)
    bare = Raw("analyst", json.dumps({"text": "The line fits with r2 0.97."}))
    with pytest.raises(AgentOutputError, match="analyst"):
        run_workflow(project, services(project, (METHOD, CODE, bare, bare)))
    assert not (project / "results.md").exists()


def test_results_md_holds_numbers_only_with_their_result_ids(project: Path) -> None:
    switch_gates_off(project)
    outcome = run_workflow(project, services(project))
    (record,) = outcome.results
    text = (project / "results.md").read_text(encoding="utf-8")
    # Finding 9 of M1-16: no dimensionless unit, the value to its tolerance.
    assert f"0.97 [{record.id}]" in text
    assert record.value == 0.97
    assert validate_project(project).problems == ()


# Reject with feedback (M1-11 review)


def _answer(project: Path, approval_id: str, decision: str, feedback: str | None) -> None:
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
        "feedback": feedback,
        "edited_artifact_id": None,
        "edited_content_hash": None,
    }
    (project / "approvals" / f"{approval_id}.response.json").write_text(
        json.dumps(response), encoding="utf-8"
    )


FEEDBACK = "Synthetic feedback: also count the rows."


def test_a_rejection_reruns_the_stage_with_the_feedback_as_input(project: Path) -> None:
    second = plan("Fit a line and count the rows", ("r2",))
    run_services = services(project, (METHOD, second, CODE))
    with pytest.raises(RunPausedError) as first:
        run_workflow(project, run_services)
    _answer(project, first.value.approval_id, "reject", FEEDBACK)
    with pytest.raises(RunPausedError) as again:
        resume_workflow(project, run_services)
    # The methodology ran again with the feedback, and the gate asks again.
    requests = _provider(run_services).of("methodologist")
    assert len(requests) == 2
    assert FEEDBACK in requests[1].messages[-1].content
    assert (project / "method.md").read_text(encoding="utf-8") == rendered(
        "Fit a line and count the rows"
    )
    assert again.value.approval_id != first.value.approval_id
    (answered,) = _events(project, EventType.APPROVAL_ANSWERED)
    assert answered.data == {
        "approval_id": first.value.approval_id,
        "decision": "reject",
        "feedback": FEEDBACK,
    }
    (route,) = _events(project, EventType.ROUTE_BACK)
    assert route.data == {
        "from_stage": "methodology",
        "to_stage": "methodology",
        "finding": "rejected_at_gate",
        "attempt": 1,
        "cap": 2,
    }


def test_rejections_beyond_the_retry_cap_pause_with_retry_limit(project: Path) -> None:
    _edit_config(project, "  retry_cap: 2\n", "  retry_cap: 1\n")
    run_services = services(project, (METHOD, METHOD, METHOD))
    with pytest.raises(RunPausedError) as first:
        run_workflow(project, run_services)
    _answer(project, first.value.approval_id, "reject", FEEDBACK)
    with pytest.raises(RunPausedError) as second:
        resume_workflow(project, run_services)
    _answer(project, second.value.approval_id, "reject", FEEDBACK)
    with pytest.raises(RunPausedError) as third:
        resume_workflow(project, run_services)
    request = load_approval_request(
        project / "approvals" / f"{third.value.approval_id}.request.json"
    )
    assert request.kind is ApprovalKind.RETRY_LIMIT
    routes = _events(project, EventType.ROUTE_BACK)
    assert [(e.status, e.data["attempt"]) for e in routes] == [
        (EventStatus.OK, 1),
        (EventStatus.REFUSED, 2),
    ]
    assert request.refused_event_id == routes[-1].event_id


# Findings of M1-16: a fenced answer, and traces of invalid answers


def _fenced(reply: object) -> str:
    return "```json\n" + json.dumps(reply, indent=2) + "\n```"


def test_an_answer_in_one_code_fence_is_taken(project: Path) -> None:
    switch_gates_off(project)
    run_services = services(project, (Raw("methodologist", _fenced(METHOD)), CODE))
    run_workflow(project, run_services)
    assert len(_provider(run_services).of("methodologist")) == 1
    assert (project / "method.md").read_text(encoding="utf-8") == METHOD_MD
    assert not (project / ".utux" / "traces").exists()


@pytest.mark.parametrize(
    "answer",
    [
        "Here is the plan.\n" + _fenced(METHOD),
        _fenced(METHOD) + "\n" + _fenced(METHOD),
    ],
    ids=["preface", "two blocks"],
)
def test_a_fence_with_more_around_it_is_invalid_and_its_text_is_kept(
    project: Path, answer: str
) -> None:
    switch_gates_off(project)
    run_services = services(project, (Raw("methodologist", answer), METHOD, CODE))
    run_workflow(project, run_services)
    calls = [
        e
        for e in _events(project, EventType.MODEL_CALL)
        if e.stage and e.stage.value == "methodology"
    ]
    assert [e.retry_reason for e in calls] == [None, "invalid_structured_output"]
    trace = project / ".utux" / "traces" / f"{calls[0].event_id}.txt"
    assert trace.read_text(encoding="utf-8") == answer


def test_a_stage_that_fails_names_the_trace_of_its_last_answer(project: Path) -> None:
    switch_gates_off(project)
    first, second = Raw("methodologist", "not json"), Raw("methodologist", "still not json")
    with pytest.raises(AgentOutputError):
        run_workflow(project, services(project, (first, second)))
    calls = _events(project, EventType.MODEL_CALL)
    (error,) = _events(project, EventType.ERROR)
    assert error.data == {"trace": f".utux/traces/{calls[1].event_id}.txt"}
    traces = project / ".utux" / "traces"
    assert (traces / f"{calls[0].event_id}.txt").read_text(encoding="utf-8") == "not json"
    assert (traces / f"{calls[1].event_id}.txt").read_text(encoding="utf-8") == "still not json"
    # Traces stay on the machine: git ignores them.
    assert ".utux/traces/" in (project / ".gitignore").read_text(encoding="utf-8")


def test_the_retry_of_an_analysis_names_the_refused_word_and_sentence(project: Path) -> None:
    switch_gates_off(project)
    bad = Raw("analyst", json.dumps({"text": "The fit is three times better: [R0001]."}))
    run_services = services(project, (METHOD, CODE, bad))
    run_workflow(project, run_services)
    _, retry = _provider(run_services).of("analyst")
    asked = retry.messages[-1].content
    assert "'three'" in asked
    assert '"The fit is three times better: [R0001]."' in asked
