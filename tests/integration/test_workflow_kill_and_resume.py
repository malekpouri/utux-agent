"""M1-10, check 1: a run killed after the implementation stage resumes from
the SQLite checkpoint in a new process and gives the same results.

"Same results" is rule 6 of the M1 plan: with the scripted model and
executor, every artifact's content hash and every result record's value are
identical, and the event log differs only by the events of the crash and
the resume.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from workflow_scripts import QUESTION, configure_models, switch_gates_off

from utux.events.log import EventLog
from utux.schemas.artifact_metadata import load_artifact_metadata
from utux.schemas.event import EventType
from utux.schemas.project_config import DataPolicy
from utux.workspace.project import init_project

CHILD = Path(__file__).resolve().parent / "workflow_child.py"


@pytest.fixture
def environment(tmp_path: Path) -> dict[str, str]:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    return {**os.environ, "GIT_CONFIG_GLOBAL": str(config), "GIT_CONFIG_NOSYSTEM": "1"}


def _project(path: Path, environment: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", environment["GIT_CONFIG_GLOBAL"])
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    project = init_project(path, budget_usd=5, data_policy=DataPolicy.LOCAL_ONLY)
    (project / "inputs" / "question.md").write_text(QUESTION, encoding="utf-8")
    configure_models(project)
    # The gates are M1-11's; these tests are about the run itself.
    switch_gates_off(project)
    return project


def _child(
    project: Path, mode: str, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHILD), str(project), mode],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
        timeout=300,
    )


def _artifact_hashes(project: Path) -> dict[str, str]:
    return {
        load_artifact_metadata(path).path: load_artifact_metadata(path).content_hash
        for path in sorted((project / ".utux" / "meta").glob("*.json"))
    }


def _record_values(project: Path) -> list[tuple[object, ...]]:
    lines = (project / "results.jsonl").read_text(encoding="utf-8").splitlines()
    return [
        tuple(json.loads(line)[k] for k in ("id", "metric", "value", "unit", "run_id"))
        for line in lines
    ]


def _event_shape(project: Path) -> list[tuple[str, str | None, object]]:
    return [
        (e.type.value, e.stage.value if e.stage else None, e.data.get("node"))
        for e in EventLog(project / "events.jsonl")
        if e.type is not EventType.RUN_RESUMED
    ]


def test_a_killed_run_resumes_in_a_new_process_with_the_same_results(
    tmp_path: Path, environment: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    killed = _project(tmp_path / "killed", environment, monkeypatch)
    whole = _project(tmp_path / "whole", environment, monkeypatch)

    first = _child(killed, "run-and-die", environment)
    assert first.returncode == -signal.SIGKILL, first.stderr
    # It died after the implementation stage was committed, before the experiment.
    ends = [
        e.data["node"] for e in EventLog(killed / "events.jsonl") if e.type is EventType.STAGE_END
    ]
    assert ends == ["methodology", "implementation"]
    assert not (killed / "results.md").exists()

    # The killed process left the project lock behind. Resume refuses until a
    # person has removed it, as documented for a crash.
    refused = _child(killed, "resume", environment)
    assert refused.returncode != 0
    assert "no longer running" in refused.stderr
    (killed / ".utux" / "lock").unlink()
    resumed = _child(killed, "resume", environment)
    assert resumed.returncode == 0, resumed.stderr
    uninterrupted = _child(whole, "run", environment)
    assert uninterrupted.returncode == 0, uninterrupted.stderr

    assert _artifact_hashes(killed) == _artifact_hashes(whole)
    assert _record_values(killed) == _record_values(whole)
    assert _event_shape(killed) == _event_shape(whole)
    assert [e.type for e in EventLog(killed / "events.jsonl")].count(EventType.RUN_RESUMED) == 1
