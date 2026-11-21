"""M1-10: the graph of stages 3 to 5, its checkpoints and its commits.

The model and the executor are scripted (workflow_scripts.py); nothing is
executed and no model is called.
"""

import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from workflow_scripts import (
    CODE,
    CODE_AFTER_EDIT,
    METHOD,
    METHOD_AFTER_QUESTION_EDIT,
    METHOD_AFTER_QUESTION_EDIT_MD,
    METHOD_MD,
    QUESTION,
    configure_models,
    services,
    switch_gates_off,
)

from utux.core.approvals import answer_approval
from utux.core.checkpoints import StrictCheckpointSerializer
from utux.core.workflow import (
    CHECKPOINT_FILE,
    FINDINGS,
    NODES,
    ROUTES,
    checkpointed_state,
    resume_workflow,
    run_workflow,
)
from utux.errors import (
    CheckpointMismatchError,
    NoRunToResumeError,
    RunPausedError,
    RunRefusedError,
)
from utux.events.log import EventLog
from utux.schemas.approval import Decision
from utux.schemas.artifact_metadata import load_artifact_metadata
from utux.schemas.event import Event, EventStatus, EventType
from utux.schemas.project_config import DataPolicy
from utux.workspace.hashing import hash_file
from utux.workspace.project import init_project
from utux.workspace.validation import validate_project
from utux.workspace.writer import record_setting_changes


class SyntheticCrashError(Exception):
    """Stands in for a crash between two stages."""


@pytest.fixture
def git_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return config


def make_project(path: Path) -> Path:
    project = init_project(path, budget_usd=5, data_policy=DataPolicy.LOCAL_ONLY)
    (project / "inputs" / "question.md").write_text(QUESTION, encoding="utf-8")
    configure_models(project)
    # The gates are M1-11's; these tests are about the run itself.
    switch_gates_off(project)
    return project


@pytest.fixture
def project(tmp_path: Path, git_config: Path) -> Path:
    return make_project(tmp_path / "p")


def _events(project: Path) -> list[Event]:
    return list(EventLog(project / "events.jsonl"))


def _git(project: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(project), *arguments], capture_output=True, text=True, check=True
    ).stdout


def _crash_before(stage: str) -> object:
    def hook(node: str) -> None:
        if node == stage:
            raise SyntheticCrashError(node)

    return hook


# A whole run


def test_a_run_goes_through_the_four_nodes(project: Path) -> None:
    outcome = run_workflow(project, services(project))
    assert NODES == ("methodology", "implementation", "experiment", "analysis")
    assert (project / "method.md").read_text(encoding="utf-8") == METHOD_MD
    assert (project / "code" / "main.py").read_text(encoding="utf-8") == CODE
    (record,) = outcome.results
    assert (record.id, record.metric, record.value, record.run_id) == ("R0001", "r2", 0.97, "r001")
    results_md = (project / "results.md").read_text(encoding="utf-8")
    assert "R0001" in results_md
    assert "0.97" in results_md
    assert validate_project(project).problems == ()


def test_each_stage_writes_sidecars_and_ends_with_an_event(project: Path) -> None:
    outcome = run_workflow(project, services(project))
    meta = project / ".utux" / "meta"
    method = load_artifact_metadata(meta / "method-v001.json")
    code = load_artifact_metadata(meta / "code-v001.json")
    metrics = load_artifact_metadata(meta / "metrics-v001.json")
    results = load_artifact_metadata(meta / "results-v001.json")
    assert (method.path, method.stage.value) == ("method.md", "methodology")
    assert (code.path, code.input_artifacts) == ("code/main.py", ("method-v001",))
    assert metrics.path == "runs/r001/outputs/metrics.json"
    assert results.path == "results.md"
    assert method.content_hash == hash_file(project / "method.md")

    stage_events = [
        (e.type, e.data.get("node"), e.stage.value if e.stage else None)
        for e in _events(project)
        if e.type in (EventType.STAGE_START, EventType.STAGE_END)
    ]
    expected = []
    for node, stage in (
        ("methodology", "methodology"),
        ("implementation", "implementation"),
        ("experiment", "experiment"),
        ("analysis", "experiment"),
    ):
        expected += [(EventType.STAGE_START, node, stage), (EventType.STAGE_END, node, stage)]
    assert stage_events == expected
    ends = [e for e in _events(project) if e.type is EventType.STAGE_END]
    assert ends[0].artifacts == ("method-v001",)
    assert all(e.run_id == outcome.run_id for e in ends)


def test_a_run_starts_with_run_started_and_its_id_names_the_run(project: Path) -> None:
    outcome = run_workflow(project, services(project))
    started = [e for e in _events(project) if e.type is EventType.RUN_STARTED]
    assert len(started) == 1
    assert started[0].event_id == outcome.run_id
    assert started[0].status is EventStatus.OK
    assert started[0].data == {"mode": "guided", "commits": True, "commit_check_reason": None}
    calls = [e for e in _events(project) if e.type is EventType.MODEL_CALL]
    assert [e.run_id for e in calls] == [outcome.run_id] * 3


def test_each_stage_is_committed(project: Path) -> None:
    outcome = run_workflow(project, services(project))
    subjects = _git(project, "log", "--format=%s").splitlines()
    assert subjects[:4] == [f"utux: {node} ({outcome.run_id})" for node in reversed(NODES)]
    assert _git(project, "status", "--porcelain") == ""


def test_the_checkpoint_is_in_utux_and_uses_the_strict_serializer(project: Path) -> None:
    outcome = run_workflow(project, services(project))
    assert CHECKPOINT_FILE == ".utux/checkpoints.sqlite"
    assert (project / CHECKPOINT_FILE).is_file()
    state, serde = checkpointed_state(project, outcome.run_id)
    assert isinstance(serde, StrictCheckpointSerializer)
    assert set(state["stages"]) == set(NODES)


_ID = re.compile(r"^(e-\d{6,}|r\d{3,}|R\d{3,}|[a-z][a-z0-9_-]*-v\d{3,})$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")


def _leaves(value: object, key: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        out: list[tuple[str, object]] = []
        for k, v in value.items():
            assert isinstance(k, str)
            # Keys are node names or relative paths.
            assert k in NODES or _PATH.match(k) or k.isidentifier(), k
            out += _leaves(v, k)
        return out
    if isinstance(value, list):
        return [leaf for item in value for leaf in _leaves(item, key)]
    return [(key, value)]


def test_graph_state_holds_only_ids_paths_hashes_and_small_enums(project: Path) -> None:
    outcome = run_workflow(project, services(project))
    state, _ = checkpointed_state(project, outcome.run_id)
    for key, value in _leaves(state):
        assert isinstance(value, str), (key, value)
        # The small enums: node names, routes and findings (M1-12).
        enums = (*NODES, *ROUTES, *FINDINGS)
        assert _ID.match(value) or _HASH.match(value) or value in enums, (key, value)
    # Neither artifact text nor model output is in the checkpoint database.
    database = (project / CHECKPOINT_FILE).read_bytes()
    assert METHOD_MD.encode() not in database
    assert CODE.encode() not in database


def test_events_are_readable_while_the_run_is_in_progress(project: Path) -> None:
    seen: dict[str, list[str]] = {}

    def look(node: str) -> None:
        seen[node] = [
            str(e.data.get("node"))
            for e in EventLog(project / "events.jsonl")
            if e.type is EventType.STAGE_END
        ]

    run_workflow(project, services(project, before_stage=look))
    assert seen["methodology"] == []
    assert seen["implementation"] == ["methodology"]
    assert seen["experiment"] == ["methodology", "implementation"]
    assert seen["analysis"] == ["methodology", "implementation", "experiment"]


def test_check_4_model_calls_executions_and_approvals_are_in_the_log_during_the_run(
    tmp_path: Path, git_config: Path
) -> None:
    # Gates on: the run pauses at each gate, is answered, and resumes.
    project = init_project(tmp_path / "gated", budget_usd=5, data_policy=DataPolicy.LOCAL_ONLY)
    (project / "inputs" / "question.md").write_text(QUESTION, encoding="utf-8")
    configure_models(project)
    seen: dict[str, set[str]] = {}

    def look(node: str) -> None:
        seen[node] = {e.type.value for e in EventLog(project / "events.jsonl")}

    for approval_id in ("a-000001", "a-000002"):
        with pytest.raises(RunPausedError):
            (run_workflow if approval_id == "a-000001" else resume_workflow)(
                project, services(project, (METHOD, CODE), before_stage=look)
            )
        answer_approval(project, approval_id, Decision.APPROVE, person="alex")
    resume_workflow(project, services(project, (CODE,), before_stage=look))
    assert {"model_call", "approval_requested", "approval_answered"} <= seen["implementation"]
    assert {"model_call", "code_execution", "approval_answered"} <= seen["analysis"]


# The commit check of ADR-0010


def _failing_signing(project: Path, tmp_path: Path) -> None:
    program = tmp_path / "sign"
    program.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    program.chmod(0o755)
    _git(project, "config", "commit.gpgsign", "true")
    _git(project, "config", "gpg.program", str(program))


def test_guided_mode_runs_without_commits_when_the_check_fails(
    project: Path, tmp_path: Path
) -> None:
    _failing_signing(project, tmp_path)
    commits_before = _git(project, "rev-list", "--count", "HEAD")
    outcome = run_workflow(project, services(project))
    assert outcome.commits is False
    (started,) = [e for e in _events(project) if e.type is EventType.RUN_STARTED]
    assert started.status is EventStatus.OK
    assert started.data == {
        "mode": "guided",
        "commits": False,
        "commit_check_reason": "commit_check_failed",
    }
    assert _git(project, "rev-list", "--count", "HEAD") == commits_before
    assert (project / "results.md").is_file()


def test_auto_mode_refuses_to_start_when_the_check_fails(project: Path, tmp_path: Path) -> None:
    _failing_signing(project, tmp_path)
    config = project / "utux.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("mode: guided", "mode: auto"), "utf-8"
    )
    with pytest.raises(RunRefusedError, match="commit"):
        run_workflow(project, services(project))
    (started,) = [e for e in _events(project) if e.type is EventType.RUN_STARTED]
    assert (started.status, started.status_reason) == (EventStatus.REFUSED, "commit_check_failed")
    assert started.data["mode"] == "auto"
    assert not (project / "method.md").exists()
    assert not (project / CHECKPOINT_FILE).exists()


# Resume: the files win


def test_a_resume_after_a_crash_continues_where_it_stopped(project: Path) -> None:
    with pytest.raises(SyntheticCrashError):
        run_workflow(project, services(project, before_stage=_crash_before("experiment")))
    outcome = resume_workflow(project, services(project, replies=()))
    assert [r.id for r in outcome.results] == ["R0001"]
    types = [e.type for e in _events(project)]
    assert EventType.RUN_RESUMED in types
    assert EventType.RUN_RESTARTED not in types
    assert validate_project(project).problems == ()


def test_an_edited_input_restarts_the_earliest_stage_that_reads_it(project: Path) -> None:
    with pytest.raises(SyntheticCrashError):
        run_workflow(project, services(project, before_stage=_crash_before("experiment")))
    (project / "method.md").write_text(METHOD_MD + "\nEdited by hand.\n", encoding="utf-8")
    outcome = resume_workflow(project, services(project, replies=(CODE_AFTER_EDIT,)))
    (restart,) = [e for e in _events(project) if e.type is EventType.RUN_RESTARTED]
    assert restart.stage is not None
    assert restart.stage.value == "implementation"
    assert restart.run_id == outcome.run_id
    assert restart.data["changed_path"] == "method.md"
    assert restart.data["actual_hash"] == hash_file(project / "method.md")
    # The implementation ran again on the edited method.
    assert (project / "code" / "main.py").read_text(encoding="utf-8") == CODE_AFTER_EDIT
    edited = load_artifact_metadata(project / ".utux" / "meta" / "method-v002.json")
    assert edited.created_by == "human:unknown"
    assert edited.input_artifacts == ("method-v001",)
    assert edited.content_hash == hash_file(project / "method.md")
    code = load_artifact_metadata(project / ".utux" / "meta" / "code-v002.json")
    assert code.input_artifacts == ("method-v002",)
    assert validate_project(project).problems == ()


def test_an_edited_question_restarts_from_methodology(project: Path) -> None:
    with pytest.raises(SyntheticCrashError):
        run_workflow(project, services(project, before_stage=_crash_before("experiment")))
    (project / "inputs" / "question.md").write_text(QUESTION + "Edited.\n", encoding="utf-8")
    resume_workflow(project, services(project, replies=(METHOD_AFTER_QUESTION_EDIT, CODE)))
    (restart,) = [e for e in _events(project) if e.type is EventType.RUN_RESTARTED]
    assert restart.stage is not None
    assert restart.stage.value == "methodology"
    assert restart.data["changed_path"] == "inputs/question.md"
    assert (project / "method.md").read_text(encoding="utf-8") == METHOD_AFTER_QUESTION_EDIT_MD


# Resume: only our own checkpoint


def test_a_checkpoint_that_no_run_started_event_matches_is_refused(
    tmp_path: Path, git_config: Path
) -> None:
    other = make_project(tmp_path / "other")
    with pytest.raises(SyntheticCrashError):
        run_workflow(other, services(other, before_stage=_crash_before("experiment")))
    project = make_project(tmp_path / "p")
    shutil.copyfile(other / CHECKPOINT_FILE, project / CHECKPOINT_FILE)
    # The hand edit of the model tier is recorded first, as by any writing
    # command (M1-05), so that only the refusal is compared.
    record_setting_changes(project)
    before = (project / "events.jsonl").read_bytes()
    with pytest.raises(CheckpointMismatchError, match="run_started"):
        resume_workflow(project, services(project, replies=()))
    assert (project / "events.jsonl").read_bytes() == before


def test_resume_without_a_checkpoint_is_refused(project: Path) -> None:
    with pytest.raises(NoRunToResumeError):
        resume_workflow(project, services(project, replies=()))


def test_the_checkpoint_database_is_sqlite(project: Path) -> None:
    run_workflow(project, services(project))
    with sqlite3.connect(project / CHECKPOINT_FILE) as connection:
        tables = {row[0] for row in connection.execute("select name from sqlite_master")}
    assert "checkpoints" in tables


# A stage that stops halfway (specification, section 7)


def _crash_inside(stage: str, point: str) -> object:
    def hook(node: str, where: str) -> None:
        if (node, where) == (stage, point):
            raise SyntheticCrashError(f"{node} {where}")

    return hook


def _versions(project: Path) -> list[str]:
    return sorted(p.stem for p in (project / ".utux" / "meta").glob("*.json"))


def test_a_node_stopped_after_writing_its_outputs_leaves_nothing_in_place(
    project: Path,
) -> None:
    with pytest.raises(SyntheticCrashError):
        run_workflow(
            project, services(project, inside_stage=_crash_inside("methodology", "staged"))
        )
    # The output and its sidecar were written, but only in the staging area.
    assert not (project / "method.md").exists()
    assert _versions(project) == []
    resume_workflow(project, services(project))
    assert _versions(project) == ["code-v001", "method-v001", "metrics-v001", "results-v001"]
    assert not (project / ".utux" / "staging").exists()
    assert validate_project(project).problems == ()


def test_an_experiment_stopped_halfway_leaves_no_extra_run(project: Path) -> None:
    with pytest.raises(SyntheticCrashError):
        run_workflow(
            project,
            services(project, runs=2, inside_stage=_crash_inside("experiment", "staged")),
        )
    assert not (project / "runs" / "r001").exists()
    outcome = resume_workflow(project, services(project, replies=()))
    assert sorted(p.name for p in (project / "runs").iterdir() if p.is_dir()) == ["r001"]
    assert [r.id for r in outcome.results] == ["R0001"]
    assert _versions(project) == ["code-v001", "method-v001", "metrics-v001", "results-v001"]


def test_a_node_stopped_after_moving_its_outputs_makes_no_new_version(project: Path) -> None:
    with pytest.raises(SyntheticCrashError):
        run_workflow(project, services(project, inside_stage=_crash_inside("methodology", "moved")))
    assert _versions(project) == ["method-v001"]
    # The node runs again and gets the same reply; the version is the same one.
    resume_workflow(project, services(project))
    assert _versions(project) == ["code-v001", "method-v001", "metrics-v001", "results-v001"]


def test_the_staging_area_is_not_in_git(project: Path) -> None:
    from utux.workspace.layout import ignored_by_git

    assert ignored_by_git(".utux/staging/methodology/method.md")
    assert ignored_by_git(".utux/staging", directory=True)


# Two kinds of run


def test_an_execution_run_id_never_has_the_form_of_a_workflow_run_id(project: Path) -> None:
    import json

    from utux.errors import ContractValidationError
    from utux.schemas.run_manifest import RunManifest

    outcome = run_workflow(project, services(project))
    manifest = json.loads((project / "runs" / "r001" / "manifest.json").read_text("utf-8"))
    assert manifest["run_id"] == "r001"
    assert outcome.run_id.startswith("e-")
    manifest["run_id"] = outcome.run_id
    with pytest.raises(ContractValidationError):
        RunManifest.from_json(json.dumps(manifest))
