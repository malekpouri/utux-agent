"""M0-08: validating every contract file of a project."""

import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from utux.schemas.project_config import DataPolicy
from utux.workspace.layout import GITIGNORE_LINES
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
    (
        "fragment_without_repair_event",
        "events.jsonl.fragment-20261116T110712.125Z",
        None,
        "<document>",
        "unrecorded_fragment",
    ),
    (
        "repair_event_without_fragment",
        "events.jsonl",
        3,
        "data.fragment_file",
        "missing_fragment_file",
    ),
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
    (
        "sidecar_content_hash_mismatch",
        ".utux/meta/method-v003.json",
        None,
        "content_hash",
        "content_hash_mismatch",
    ),
    (
        "sidecar_input_without_sidecar",
        ".utux/meta/method-v003.json",
        None,
        "input_artifacts.1",
        "unknown_reference",
    ),
    ("sidecar_artifact_file_missing", ".utux/meta/idea-v002.json", None, "path", "missing_file"),
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
    # utux.yaml, the three .jsonl files, three sidecars, one source record,
    # one manifest, one approval request and one response. The artifact files
    # the sidecars describe are hashed but are not contract files.
    assert report.files_checked == 11


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
        "files_checked": 11,
        "problems": [
            {
                "file": "results.jsonl",
                "line": 2,
                "field": "id",
                "code": "duplicate_id",
                "reason": "R0042 is already used on line 1",
            }
        ],
        "warnings": [],
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


# Fragment side files of utux log repair


FRAGMENT = b'{"schema_version": 1, "event_'
FRAGMENT_FILE = "events.jsonl.fragment-20261116T110712.125Z"


def _with_repair_event(tmp_path: Path, **data: object) -> Path:
    """A valid project with a fragment side file and a log_repaired event for it."""
    from utux.workspace.hashing import hash_bytes

    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    (project / FRAGMENT_FILE).write_bytes(FRAGMENT)
    lines = (project / "events.jsonl").read_text(encoding="utf-8")
    event = json.loads(lines.split("\n")[1])
    event.update(
        event_id="e-000003",
        type="log_repaired",
        actor="system:utux",
        data={
            "fragment_file": FRAGMENT_FILE,
            "fragment_hash": hash_bytes(FRAGMENT),
            "fragment_bytes": len(FRAGMENT),
            **data,
        },
    )
    (project / "events.jsonl").write_text(lines + json.dumps(event) + "\n", encoding="utf-8")
    return project


def test_recorded_fragment_is_valid(tmp_path: Path) -> None:
    report = validate_project(_with_repair_event(tmp_path))
    assert report.problems == ()
    assert report.files_checked == 12


def test_fragment_of_another_length_is_reported_on_the_event(tmp_path: Path) -> None:
    project = _with_repair_event(tmp_path, fragment_bytes=len(FRAGMENT) + 1)
    (problem,) = validate_project(project).problems
    assert (problem.file, problem.line, problem.field, problem.code) == (
        "events.jsonl",
        3,
        "data.fragment_bytes",
        "fragment_mismatch",
    )
    assert problem.reason == (f"{FRAGMENT_FILE} has {len(FRAGMENT)} bytes, not {len(FRAGMENT) + 1}")


def test_fragment_with_another_hash_is_reported_on_the_event(tmp_path: Path) -> None:
    project = _with_repair_event(tmp_path, fragment_hash="sha256:" + "0" * 64)
    assert _found(validate_project(project)) == [
        ("events.jsonl", 3, "data.fragment_hash", "fragment_mismatch")
    ]


@pytest.mark.parametrize(
    "name", ["../outside", "sub/events.jsonl.fragment-x", "notes.txt", "events.jsonl.fragment-"]
)
def test_fragment_file_must_be_a_fragment_name_beside_the_log(tmp_path: Path, name: str) -> None:
    """The name comes from the log, so it is checked before any file is opened."""
    (tmp_path / "outside").write_bytes(FRAGMENT)
    project = _with_repair_event(tmp_path, fragment_file=name)
    found = _found(validate_project(project))
    assert ("events.jsonl", 3, "data.fragment_file", "invalid_fragment_file") in found


def test_every_side_file_and_every_event_is_checked(tmp_path: Path) -> None:
    project = _with_repair_event(tmp_path)
    (project / "events.jsonl.fragment-20261116T120000.000Z").write_bytes(b"x")
    assert _found(validate_project(project)) == [
        ("events.jsonl.fragment-20261116T120000.000Z", None, "<document>", "unrecorded_fragment")
    ]


# Sidecars and the files they describe (M1-03)

_SIDECAR = {
    "artifact_id": "method-v004",
    "path": "method.md",
    "stage": "methodology",
    "schema_version": 1,
    "created_by": "agent:methodologist",
    "created_at": "2026-11-16T10:00:00Z",
    "input_artifacts": ["idea-v002", "literature-v004"],
    "content_hash": "sha256:" + "1" * 64,
    "state": "valid",
}


def _copy_valid(tmp_path: Path) -> Path:
    project = tmp_path / "p"
    shutil.copytree(VALID, project)
    return project


def _add_sidecar(project: Path, file_name: str, **fields: object) -> None:
    document = {**_SIDECAR, **fields}
    path = project / ".utux" / "meta" / file_name
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def test_only_the_current_version_of_a_path_is_checked_against_the_file(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    # An older version of method.md, whose content is no longer the file's.
    _add_sidecar(project, "method-v002.json", artifact_id="method-v002", input_artifacts=[])
    assert validate_project(project).problems == ()


def test_the_highest_version_is_the_current_one(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    _add_sidecar(project, "method-v004.json")
    # method-v004 is now current and its hash is not the file's; method-v003
    # is an older version and is not checked.
    assert _found(validate_project(project)) == [
        (".utux/meta/method-v004.json", None, "content_hash", "content_hash_mismatch"),
    ]


def test_the_mismatch_names_both_hashes(tmp_path: Path) -> None:
    project = build("sidecar_content_hash_mismatch", tmp_path)
    (problem,) = validate_project(project).problems
    # sha256sum of "synthetic fixture content, edited by hand\n".
    actual = "sha256:" + hashlib.sha256(b"synthetic fixture content, edited by hand\n").hexdigest()
    assert actual in problem.reason
    recorded = "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41"
    assert recorded in problem.reason


def test_two_sidecars_with_the_same_artifact_id_are_reported(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    copy = (project / ".utux" / "meta" / "method-v003.json").read_text(encoding="utf-8")
    (project / ".utux" / "meta" / "zz-v001.json").write_text(copy, encoding="utf-8")
    assert _found(validate_project(project)) == [
        (".utux/meta/zz-v001.json", None, "artifact_id", "duplicate_id"),
        (".utux/meta/zz-v001.json", None, "artifact_id", "name_mismatch"),
    ]


def test_an_input_whose_sidecar_is_invalid_is_not_unknown(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    path = project / ".utux" / "meta" / "literature-v004.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"valid"', '"unknown"'), "utf-8")
    # The bad sidecar is reported once, on itself, and not again on method-v003.
    assert _found(validate_project(project)) == [
        (".utux/meta/literature-v004.json", None, "state", "enum"),
    ]


def test_two_sidecars_with_the_same_version_of_one_path_are_reported(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    _add_sidecar(project, "plan-v003.json", artifact_id="plan-v003")
    assert _found(validate_project(project)) == [
        (".utux/meta/plan-v003.json", None, "artifact_id", "duplicate_version"),
    ]


def test_a_directory_artifact_is_checked_with_the_directory_hash(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    (project / "code" / "train.py").write_bytes(b"print('synthetic')\n")
    (project / "code" / "__pycache__").mkdir()
    (project / "code" / "__pycache__" / "train.cpython-312.pyc").write_bytes(b"\x00")
    # The documented format: one entry per file, path NUL hex newline, sorted;
    # .gitkeep and __pycache__ are left out of project content.
    entry = b"train.py\0" + hashlib.sha256(b"print('synthetic')\n").hexdigest().encode() + b"\n"
    expected = "sha256:" + hashlib.sha256(entry).hexdigest()
    _add_sidecar(
        project, "code-v001.json", artifact_id="code-v001", path="code", content_hash=expected
    )
    assert validate_project(project).problems == ()
    (project / "code" / "train.py").write_bytes(b"print('changed')\n")
    assert _found(validate_project(project)) == [
        (".utux/meta/code-v001.json", None, "content_hash", "content_hash_mismatch"),
    ]


def test_a_path_that_leads_outside_the_project_is_not_read(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("synthetic fixture content\n", encoding="utf-8")
    (project / "method.md").unlink()
    (project / "method.md").symlink_to(outside)
    assert _found(validate_project(project)) == [
        (".utux/meta/method-v003.json", None, "path", "path_outside_project"),
    ]


def test_a_directory_that_cannot_be_hashed_is_reported(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    (project / "code" / "link.py").symlink_to(project / "method.md")
    _add_sidecar(project, "code-v001.json", artifact_id="code-v001", path="code")
    assert _found(validate_project(project)) == [
        (".utux/meta/code-v001.json", None, "path", "unhashable"),
    ]


# Files kept out of git (M1-03, ADR-0009)


def test_a_missing_untracked_file_is_a_warning(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    _add_sidecar(
        project,
        "data-v001.json",
        artifact_id="data-v001",
        path="inputs/data.csv",
        stage="ideation",
        input_artifacts=[],
    )
    report = validate_project(project)
    assert report.problems == ()
    assert report.valid is True
    assert [(w.file, w.line, w.field, w.code) for w in report.warnings] == [
        (".utux/meta/data-v001.json", None, "path", "missing_untracked_file"),
    ]
    assert "inputs/data.csv" in report.warnings[0].reason


def test_a_missing_run_output_directory_is_a_warning(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    _add_sidecar(
        project,
        "outputs-v001.json",
        artifact_id="outputs-v001",
        path="runs/r012/outputs",
        stage="experiment",
        input_artifacts=[],
    )
    report = validate_project(project)
    assert report.problems == ()
    assert [w.code for w in report.warnings] == ["missing_untracked_file"]


def test_a_missing_tracked_file_stays_an_error(tmp_path: Path) -> None:
    report = validate_project(build("sidecar_artifact_file_missing", tmp_path))
    assert report.warnings == ()
    assert _found(report) == [(".utux/meta/idea-v002.json", None, "path", "missing_file")]


def test_a_present_untracked_file_is_still_checked(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    (project / "inputs" / "data.csv").write_bytes(b"a,b\n1,2\n")
    _add_sidecar(
        project,
        "data-v001.json",
        artifact_id="data-v001",
        path="inputs/data.csv",
        stage="ideation",
        input_artifacts=[],
    )
    assert _found(validate_project(project)) == [
        (".utux/meta/data-v001.json", None, "content_hash", "content_hash_mismatch"),
    ]


def _git(directory: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=directory, check=True, capture_output=True)


def test_a_fresh_clone_without_its_untracked_files_has_warnings_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    project = _copy_valid(tmp_path)
    (project / ".gitignore").write_text("\n".join(GITIGNORE_LINES) + "\n", encoding="utf-8")
    data = b"a,b\n1,2\n"
    output = b"synthetic model weights\n"
    (project / "inputs" / "data.csv").write_bytes(data)
    (project / "runs" / "r012" / "outputs").mkdir()
    (project / "runs" / "r012" / "outputs" / "model.bin").write_bytes(output)
    _add_sidecar(
        project,
        "data-v001.json",
        artifact_id="data-v001",
        path="inputs/data.csv",
        stage="ideation",
        input_artifacts=[],
        content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
    )
    _add_sidecar(
        project,
        "model-v001.json",
        artifact_id="model-v001",
        path="runs/r012/outputs/model.bin",
        stage="experiment",
        input_artifacts=["data-v001"],
        content_hash="sha256:" + hashlib.sha256(output).hexdigest(),
    )
    assert validate_project(project).problems == ()
    _git(project, "init", "-q", "-b", "main")
    _git(project, "add", "-A")
    _git(project, "commit", "-q", "-m", "Synthetic project")
    _git(tmp_path, "clone", "-q", str(project), "clone")
    clone = tmp_path / "clone"
    assert not (clone / "inputs" / "data.csv").exists()
    assert not (clone / "runs" / "r012" / "outputs").exists()

    report = validate_project(clone)
    assert report.problems == ()
    assert report.valid is True
    assert sorted((w.file, w.code) for w in report.warnings) == [
        (".utux/meta/data-v001.json", "missing_untracked_file"),
        (".utux/meta/model-v001.json", "missing_untracked_file"),
    ]


# Approval kinds (M1-04)

_UNBOUND_REQUEST = {
    "schema_version": 1,
    "approval_id": "a-000009",
    "kind": "budget_exhausted",
    "gate": None,
    "artifact_id": None,
    "content_hash": None,
    "path": None,
    "stage": "implementation",
    "refused_event_id": "e-000001",
    "requested_by": "system:utux",
    "requested_at": "2026-11-16T14:00:00Z",
}


def _with_unbound_request(tmp_path: Path, **changes: object) -> Path:
    project = _copy_valid(tmp_path)
    document = {**_UNBOUND_REQUEST, **changes}
    (project / "approvals" / "a-000009.request.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    return project


def test_an_unbound_request_whose_refused_call_is_in_the_log_is_valid(tmp_path: Path) -> None:
    assert validate_project(_with_unbound_request(tmp_path)).problems == ()


def test_an_unbound_request_must_name_an_event_of_the_log(tmp_path: Path) -> None:
    project = _with_unbound_request(tmp_path, refused_event_id="e-000999")
    assert _found(validate_project(project)) == [
        ("approvals/a-000009.request.json", None, "refused_event_id", "unknown_reference"),
    ]


def test_a_response_of_another_kind_than_its_request_is_reported(tmp_path: Path) -> None:
    project = _with_unbound_request(tmp_path)
    response = {
        "schema_version": 1,
        "approval_id": "a-000009",
        "kind": "retry_limit",
        "artifact_id": None,
        "content_hash": None,
        "decision": "approve",
        "answered_by": "human:alex",
        "answered_at": "2026-11-16T14:30:00Z",
        "feedback": None,
        "edited_artifact_id": None,
        "edited_content_hash": None,
    }
    (project / "approvals" / "a-000009.response.json").write_text(
        json.dumps(response), encoding="utf-8"
    )
    assert _found(validate_project(project)) == [
        ("approvals/a-000009.response.json", None, "kind", "differs_from_request"),
    ]


# The ignore lines of ADR-0009 (M1-05)


def test_a_gitignore_without_the_lines_of_adr_0009_is_a_warning(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    (project / ".gitignore").write_text(".DS_Store\n__pycache__/\n", encoding="utf-8")
    report = validate_project(project)
    assert report.valid is True
    assert [(w.file, w.field, w.code) for w in report.warnings] == [
        (".gitignore", "<document>", "gitignore_missing_lines"),
    ]
    assert "inputs/**" in report.warnings[0].reason
    assert "runs/*/outputs/" in report.warnings[0].reason


def test_a_missing_gitignore_is_a_warning(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    (project / ".gitignore").unlink()
    report = validate_project(project)
    assert report.problems == ()
    assert [w.code for w in report.warnings] == ["gitignore_missing_lines"]


def test_a_complete_gitignore_gives_no_warning(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    assert validate_project(project).warnings == ()


# human:unknown, the maker of a version edited outside utux (M1-10)


def test_an_edit_outside_utux_may_be_made_by_human_unknown(tmp_path: Path) -> None:
    project = _copy_valid(tmp_path)
    (project / "method.md").write_text("synthetic fixture content, edited\n", encoding="utf-8")
    edited = "sha256:" + hashlib.sha256(b"synthetic fixture content, edited\n").hexdigest()
    _add_sidecar(
        project,
        "method-v004.json",
        created_by="human:unknown",
        input_artifacts=["method-v003"],
        content_hash=edited,
    )
    assert validate_project(project).problems == ()


@pytest.mark.parametrize(
    "inputs", [[], ["idea-v002"], ["method-v003", "idea-v002"], ["method-v005"]]
)
def test_human_unknown_is_allowed_only_for_an_edit_of_the_version_before(
    tmp_path: Path, inputs: list[str]
) -> None:
    project = _copy_valid(tmp_path)
    _add_sidecar(
        project,
        "method-v004.json",
        created_by="human:unknown",
        input_artifacts=inputs,
        content_hash="sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41",
    )
    found = [p for p in _found(validate_project(project)) if p[3] == "edit_actor_misused"]
    assert found == [(".utux/meta/method-v004.json", None, "created_by", "edit_actor_misused")]
