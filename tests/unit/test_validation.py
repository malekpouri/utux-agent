"""M0-08: validating every contract file of a project."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from utux.schemas.project_config import DataPolicy
from utux.workspace.project import init_project
from utux.workspace.validation import ValidationProblem, ValidationReport, validate_project

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "projects"
VALID = FIXTURES / "valid_full"

# One row per corrupted fixture project: name, and the one problem it must
# yield as (file, line, field, code). No row repeats another's problem.
CORRUPTED: list[tuple[str, str, int | None, str, str]] = [
    ("missing_events_log", "events.jsonl", None, "<document>", "missing_file"),
    ("missing_claim_ledger", "claims.jsonl", None, "<document>", "missing_file"),
    ("config_unknown_key", "utux.yaml", None, "colour", "unknown_key"),
    ("config_newer_schema_version", "utux.yaml", None, "schema_version", "schema_version_newer"),
    ("event_unknown_type", "events.jsonl", 2, "type", "enum"),
    ("event_log_incomplete_last_line", "events.jsonl", 2, "<document>", "incomplete_line"),
    ("event_ids_not_increasing", "events.jsonl", 2, "event_id", "event_id_not_increasing"),
    (
        "event_first_not_project_created",
        "events.jsonl",
        1,
        "type",
        "first_event_not_project_created",
    ),
    ("event_parent_unknown", "events.jsonl", 2, "parent_id", "unknown_reference"),
    ("result_run_without_manifest", "results.jsonl", 1, "run_id", "unknown_reference"),
    ("source_evidence_unknown", "claims.jsonl", 2, "evidence.0.source_id", "unknown_reference"),
    (
        "source_record_duplicate",
        "sources/duplicate-of-example.json",
        None,
        "source_id",
        "duplicate_id",
    ),
    ("claim_line_not_json", "claims.jsonl", 2, "<document>", "invalid_json"),
    ("claim_duplicate_id", "claims.jsonl", 4, "id", "duplicate_id"),
    ("result_duplicate_id", "results.jsonl", 2, "id", "duplicate_id"),
    ("result_evidence_unknown", "claims.jsonl", 1, "evidence.0.id", "unknown_reference"),
    ("claim_evidence_unknown", "claims.jsonl", 3, "evidence.1.id", "unknown_reference"),
    ("sidecar_unknown_state", ".utux/meta/method-v003.json", None, "state", "enum"),
    ("sidecar_name_mismatch", ".utux/meta/method-v004.json", None, "artifact_id", "name_mismatch"),
    (
        "sidecar_newer_schema_version",
        ".utux/meta/method-v003.json",
        None,
        "schema_version",
        "schema_version_newer",
    ),
    ("unexpected_file_in_meta", ".utux/meta/notes.txt", None, "<document>", "unexpected_file"),
    ("manifest_in_wrong_run_directory", "runs/r099/manifest.json", None, "run_id", "name_mismatch"),
    ("manifest_missing_seeds", "runs/r012/manifest.json", None, "seeds", "missing"),
    (
        "source_record_without_licence",
        "sources/doi-10.0000-example.json",
        None,
        "licence",
        "missing",
    ),
    (
        "approval_response_without_request",
        "approvals/a-000007.response.json",
        None,
        "<document>",
        "request_missing",
    ),
    (
        "approval_response_for_other_content",
        "approvals/a-000007.response.json",
        None,
        "content_hash",
        "differs_from_request",
    ),
    (
        "approval_file_name_mismatch",
        "approvals/a-000008.request.json",
        None,
        "approval_id",
        "name_mismatch",
    ),
]


def build(name: str, tmp_path: Path) -> Path:
    """Build a corrupted fixture project: valid_full with its overlay applied."""
    project = tmp_path / name
    shutil.copytree(VALID, project)
    overlay = FIXTURES / "corrupted" / name
    for path in sorted(overlay.rglob("*")):
        relative = path.relative_to(overlay)
        if path.is_dir() or relative.as_posix() == "remove.txt":
            continue
        (project / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, project / relative)
    remove = overlay / "remove.txt"
    if remove.exists():
        for relative in remove.read_text(encoding="utf-8").split():
            (project / relative).unlink()
    return project


def _found(report: ValidationReport) -> list[tuple[str, int | None, str, str]]:
    return [(p.file, p.line, p.field, p.code) for p in report.problems]


# Valid projects


def test_valid_fixture_project_has_no_problems() -> None:
    report = validate_project(VALID)
    assert report.problems == ()
    assert report.valid is True
    # utux.yaml, the three .jsonl files, one sidecar, one source record, one
    # manifest, one approval request and one response.
    assert report.files_checked == 9


def test_fresh_project_from_init_is_valid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    project = init_project(
        tmp_path / "fresh",
        budget_usd=20,
        data_policy=DataPolicy.LOCAL_ONLY,
        clock=lambda: datetime(2026, 11, 16, 9, 0, tzinfo=UTC),
    )
    report = validate_project(project)
    assert report.problems == ()
    assert report.files_checked == 4


def test_validation_changes_nothing(tmp_path: Path) -> None:
    project = build("several_problems", tmp_path)
    before = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    validate_project(project)
    assert {p: p.read_bytes() for p in project.rglob("*") if p.is_file()} == before


def test_files_that_are_not_contracts_are_left_alone(tmp_path: Path) -> None:
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    (project / "code" / "train.py").write_text("print('synthetic')\n", encoding="utf-8")
    (project / "paper" / "draft.tex").write_text("synthetic\n", encoding="utf-8")
    (project / "runs" / "r012" / "log.txt").write_text("synthetic log\n", encoding="utf-8")
    (project / "sources" / "notes.md").write_text("synthetic\n", encoding="utf-8")
    assert validate_project(project).problems == ()


def test_run_directory_without_a_manifest_is_accepted(tmp_path: Path) -> None:
    """A run that has not ended has no manifest yet."""
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    (project / "runs" / "r013").mkdir()
    (project / "runs" / "r013" / "log.txt").write_text("running\n", encoding="utf-8")
    assert validate_project(project).problems == ()


def test_pending_request_without_a_response_is_accepted(tmp_path: Path) -> None:
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    (project / "approvals" / "a-000007.response.json").unlink()
    assert validate_project(project).problems == ()


# Corrupted projects


def test_every_corrupted_fixture_is_listed() -> None:
    on_disk = sorted(path.name for path in (FIXTURES / "corrupted").iterdir())
    assert on_disk == sorted([row[0] for row in CORRUPTED] + ["several_problems"])
    problems = [row[1:] for row in CORRUPTED]
    assert len(set(problems)) == len(problems)


@pytest.mark.parametrize("row", CORRUPTED, ids=[row[0] for row in CORRUPTED])
def test_corrupted_project_yields_its_one_problem(
    tmp_path: Path, row: tuple[str, str, int | None, str, str]
) -> None:
    name, *expected = row
    report = validate_project(build(name, tmp_path))
    assert report.valid is False
    assert _found(report) == [tuple(expected)]
    (problem,) = report.problems
    # The message names the file, the field and the reason.
    where = problem.file if problem.line is None else f"{problem.file}:{problem.line}"
    assert problem.reason
    assert problem.message == f"{where}: {problem.field}: {problem.reason}"


def test_all_problems_are_reported_not_only_the_first(tmp_path: Path) -> None:
    report = validate_project(build("several_problems", tmp_path))
    assert sorted(_found(report), key=str) == sorted(
        [
            ("utux.yaml", None, "colour", "unknown_key"),
            ("events.jsonl", None, "<document>", "missing_file"),
            ("results.jsonl", 2, "id", "duplicate_id"),
            (".utux/meta/method-v003.json", None, "state", "enum"),
        ],
        key=str,
    )


def test_every_bad_line_of_a_file_is_reported(tmp_path: Path) -> None:
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    lines = (project / "results.jsonl").read_text(encoding="utf-8")
    (project / "results.jsonl").write_text(lines + "not json\n" + lines + "[]\n", encoding="utf-8")
    assert _found(validate_project(project)) == [
        ("results.jsonl", 2, "<document>", "invalid_json"),
        ("results.jsonl", 3, "id", "duplicate_id"),
        ("results.jsonl", 4, "<document>", "not_a_mapping"),
    ]


def test_newer_schema_version_says_so(tmp_path: Path) -> None:
    report = validate_project(build("config_newer_schema_version", tmp_path))
    (problem,) = report.problems
    assert "newer schema version" in problem.reason
    assert report.newer_schema_version is True
    assert validate_project(VALID).newer_schema_version is False


def test_duplicate_id_names_the_first_line(tmp_path: Path) -> None:
    (problem,) = validate_project(build("claim_duplicate_id", tmp_path)).problems
    assert problem.reason == "C017 is already used on line 1"


def test_unknown_reference_names_the_file_it_should_be_in(tmp_path: Path) -> None:
    (problem,) = validate_project(build("result_evidence_unknown", tmp_path)).problems
    assert problem.reason == "R0099 is not a result record in results.jsonl"


def test_reference_to_an_invalid_line_is_not_reported_again(tmp_path: Path) -> None:
    """A bad line is reported once; claims that cite its id are not reported for it."""
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    record = json.loads((project / "results.jsonl").read_text(encoding="utf-8"))
    record["tolerance"] = -1
    (project / "results.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert _found(validate_project(project)) == [
        ("results.jsonl", 1, "tolerance", "greater_than_equal")
    ]


# Paths in the report


def test_reported_paths_are_relative_to_the_project(tmp_path: Path) -> None:
    project = build("several_problems", tmp_path)
    report = validate_project(project)
    for problem in report.problems:
        assert not problem.file.startswith("/")
        assert str(tmp_path) not in problem.message
    assert str(tmp_path) not in report.to_json()


def test_directory_that_does_not_exist_is_a_problem(tmp_path: Path) -> None:
    report = validate_project(tmp_path / "nothing")
    assert _found(report) == [(".", None, "<document>", "not_a_directory")]


# The JSON report


def test_json_report_is_machine_readable(tmp_path: Path) -> None:
    report = validate_project(build("result_duplicate_id", tmp_path))
    data = json.loads(report.to_json())
    assert data == {
        "schema_version": 1,
        "valid": False,
        "newer_schema_version": False,
        "files_checked": 9,
        "problems": [
            {
                "file": "results.jsonl",
                "line": 2,
                "field": "id",
                "code": "duplicate_id",
                "reason": "R0042 is already used on line 1",
            }
        ],
    }


def test_json_report_of_a_valid_project() -> None:
    data = json.loads(validate_project(VALID).to_json())
    assert data["valid"] is True
    assert data["problems"] == []


def test_problem_is_a_plain_value() -> None:
    problem = ValidationProblem("utux.yaml", None, "colour", "unknown_key", "unknown key")
    assert problem.message == "utux.yaml: colour: unknown key"


# Lines are split on "\n" only


def test_line_separators_inside_a_line_do_not_split_it() -> None:
    """U+2028 and U+0085 are line breaks to str.splitlines(), but not in JSON Lines."""
    raw = (VALID / "claims.jsonl").read_text(encoding="utf-8")
    assert "\u2028" in raw
    assert "\u0085" in raw
    assert raw.count("\n") == 4
    assert len(raw.splitlines()) > 4  # what a wrong split would see
    report = validate_project(VALID)
    assert report.problems == ()
    last = json.loads(raw.split("\n")[3])
    assert last["id"] == "C041"
    assert "\u2028" in last["text"]
    assert "\u0085" in last["text"]


def test_carriage_return_line_ends_are_accepted(tmp_path: Path) -> None:
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    text = (project / "results.jsonl").read_text(encoding="utf-8")
    (project / "results.jsonl").write_bytes(text.replace("\n", "\r\n").encode())
    assert validate_project(project).problems == ()


def test_blank_line_in_the_middle_is_reported(tmp_path: Path) -> None:
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    text = (project / "results.jsonl").read_text(encoding="utf-8")
    (project / "results.jsonl").write_text("\n" + text, encoding="utf-8")
    assert _found(validate_project(project)) == [("results.jsonl", 1, "<document>", "invalid_json")]


# Reasons of the checks across files


def test_unknown_parent_reason(tmp_path: Path) -> None:
    (problem,) = validate_project(build("event_parent_unknown", tmp_path)).problems
    assert problem.reason == "e-000003 is not an event in events.jsonl"


def test_run_without_manifest_reason(tmp_path: Path) -> None:
    (problem,) = validate_project(build("result_run_without_manifest", tmp_path)).problems
    assert problem.reason == "r099 has no run manifest runs/r099/manifest.json"


def test_source_without_record_reason(tmp_path: Path) -> None:
    (problem,) = validate_project(build("source_evidence_unknown", tmp_path)).problems
    assert problem.reason == "doi:10.0000/other has no source record in sources/"


def test_duplicate_source_record_names_the_other_file(tmp_path: Path) -> None:
    (problem,) = validate_project(build("source_record_duplicate", tmp_path)).problems
    assert problem.reason == (
        "doi:10.0000/example is already used by sources/doi-10.0000-example.json"
    )


def test_first_event_reason(tmp_path: Path) -> None:
    (problem,) = validate_project(build("event_first_not_project_created", tmp_path)).problems
    assert (
        problem.reason == "the first event of the log must be project_created, not setting_changed"
    )


def test_reference_to_an_invalid_source_record_is_not_reported_again(tmp_path: Path) -> None:
    report = validate_project(build("source_record_without_licence", tmp_path))
    assert [p.code for p in report.problems] == ["missing"]


def test_run_whose_manifest_is_invalid_still_counts_as_existing(tmp_path: Path) -> None:
    report = validate_project(build("manifest_missing_seeds", tmp_path))
    assert [p.code for p in report.problems] == ["missing"]
