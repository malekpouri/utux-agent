"""Validation of every contract file of a project.

`validate_project` reads every contract file of a project, checks it
against its schema, and checks the rules that span lines or files: ids are
unique within `claims.jsonl` and `results.jsonl`, evidence ids refer to
existing lines, file names match the ids they hold, and an approval response
matches its request. It reports every problem it finds, not only the first,
and changes nothing.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from utux.errors import DOCUMENT_FIELD, ContractValidationError
from utux.schemas.approval import (
    ApprovalRequest,
    ApprovalResponse,
    check_response_matches_request,
)
from utux.schemas.artifact_metadata import ArtifactMetadata
from utux.schemas.base import ContractDocument
from utux.schemas.claim_ledger import ClaimEvidence, ClaimLedgerEntry, ResultRecordEvidence
from utux.schemas.event import Event, event_number, format_event_id
from utux.schemas.json_io import parse_json
from utux.schemas.project_config import ProjectConfig
from utux.schemas.result_record import ResultRecord
from utux.schemas.run_manifest import RunManifest
from utux.schemas.source_record import SourceRecord
from utux.schemas.yaml_io import parse_yaml
from utux.workspace.layout import (
    CLAIM_LEDGER_FILE,
    CONFIG_FILE,
    EVENT_LOG_FILE,
    GITKEEP_FILE,
    RESULTS_FILE,
)

REPORT_SCHEMA_VERSION = 1
META_DIRECTORY = ".utux/meta"
SOURCES_DIRECTORY = "sources"
RUNS_DIRECTORY = "runs"
APPROVALS_DIRECTORY = "approvals"
MANIFEST_FILE = "manifest.json"

_APPROVAL_FILE = re.compile(r"^(?P<id>.+)\.(?P<kind>request|response)\.json$")


@dataclass(frozen=True)
class ValidationProblem:
    """One problem in one file of a project.

    Attributes:
        file: The file, relative to the project directory, with `/`.
        line: The line, counted from 1, for a file with one record per line;
            otherwise None.
        field: The field, as a dotted path, or `<document>`.
        code: A stable code for the kind of problem.
        reason: One line for a person.
    """

    file: str
    line: int | None
    field: str
    code: str
    reason: str

    @property
    def message(self) -> str:
        """The problem as `file[:line]: field: reason`."""
        where = self.file if self.line is None else f"{self.file}:{self.line}"
        return f"{where}: {self.field}: {self.reason}"


@dataclass(frozen=True)
class ValidationReport:
    """The result of validating a project.

    Attributes:
        problems: Every problem found, in the order the files were checked.
        files_checked: How many contract files were read.
    """

    problems: tuple[ValidationProblem, ...]
    files_checked: int

    @property
    def valid(self) -> bool:
        """Whether the project has no problem."""
        return not self.problems

    @property
    def newer_schema_version(self) -> bool:
        """Whether a file was written by a newer version of utux."""
        return any(problem.code == "schema_version_newer" for problem in self.problems)

    def to_json(self) -> str:
        """Return the report as JSON text. It holds no absolute path."""
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "valid": self.valid,
            "newer_schema_version": self.newer_schema_version,
            "files_checked": self.files_checked,
            "problems": [
                {
                    "file": problem.file,
                    "line": problem.line,
                    "field": problem.field,
                    "code": problem.code,
                    "reason": problem.reason,
                }
                for problem in self.problems
            ],
        }
        return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


@dataclass
class _Line:
    """One line of a `.jsonl` file, as far as it could be read."""

    number: int
    raw_id: str | None
    document: ContractDocument | None


class _Validator:
    def __init__(self, project: Path) -> None:
        self.project = project
        self.problems: list[ValidationProblem] = []
        self.files_checked = 0

    def add(self, file: str, line: int | None, field: str, code: str, reason: str) -> None:
        self.problems.append(ValidationProblem(file, line, field, code, reason))

    def add_error(self, file: str, line: int | None, error: ContractValidationError) -> None:
        for problem in error.problems:
            self.add(file, line, problem.field, problem.code, problem.reason)

    def relative(self, path: Path) -> str:
        return path.relative_to(self.project).as_posix()

    def read_text(self, file: str) -> str | None:
        """Read a file of the project, or report why it cannot be read."""
        path = self.project / file
        if not path.is_file():
            self.add(file, None, DOCUMENT_FIELD, "missing_file", "the file is missing")
            return None
        self.files_checked += 1
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            detail = error.strerror if isinstance(error, OSError) else "not UTF-8 text"
            self.add(file, None, DOCUMENT_FIELD, "unreadable", f"the file cannot be read: {detail}")
            return None

    def document[T: ContractDocument](self, model: type[T], file: str) -> T | None:
        """Read and validate a contract file that holds one JSON document."""
        text = self.read_text(file)
        if text is None:
            return None
        try:
            return model.validate_document(parse_json(text, file), file)
        except ContractValidationError as error:
            self.add_error(file, None, error)
            return None

    # Files

    def config(self) -> None:
        text = self.read_text(CONFIG_FILE)
        if text is None:
            return
        try:
            ProjectConfig.validate_document(parse_yaml(text, CONFIG_FILE), CONFIG_FILE)
        except ContractValidationError as error:
            self.add_error(CONFIG_FILE, None, error)

    def events(self) -> None:
        path = self.project / EVENT_LOG_FILE
        if not path.is_file():
            self.add(EVENT_LOG_FILE, None, DOCUMENT_FIELD, "missing_file", "the file is missing")
            return
        self.files_checked += 1
        previous: tuple[int, int] | None = None  # number of the last valid event, and its line
        with path.open("rb") as stream:
            # Read line by line, so a long log is never held in memory.
            for number, raw in enumerate(stream, start=1):
                if not raw.endswith(b"\n"):
                    self.add(
                        EVENT_LOG_FILE,
                        number,
                        DOCUMENT_FIELD,
                        "incomplete_line",
                        "the line is incomplete; a write to the log was interrupted",
                    )
                    continue
                text = raw.decode("utf-8", errors="replace")
                try:
                    event = Event.validate_document(
                        parse_json(text, EVENT_LOG_FILE), EVENT_LOG_FILE
                    )
                except ContractValidationError as error:
                    self.add_error(EVENT_LOG_FILE, number, error)
                    continue
                current = event_number(event.event_id)
                if previous is not None and current <= previous[0]:
                    self.add(
                        EVENT_LOG_FILE,
                        number,
                        "event_id",
                        "event_id_not_increasing",
                        f"{event.event_id} is not greater than "
                        f"{format_event_id(previous[0])} on line {previous[1]}",
                    )
                    continue
                previous = (current, number)

    def lines[T: ContractDocument](self, model: type[T], file: str) -> list[_Line] | None:
        """Read a `.jsonl` file of records with ids. None if the file is missing."""
        text = self.read_text(file)
        if text is None:
            return None
        lines: list[_Line] = []
        first_use: dict[str, int] = {}
        for number, content in enumerate(text.splitlines(), start=1):
            raw_id: str | None = None
            document: T | None = None
            try:
                data = parse_json(content, file)
                if isinstance(data, dict) and isinstance(data.get("id"), str):
                    raw_id = data["id"]
                document = model.validate_document(data, file)
            except ContractValidationError as error:
                self.add_error(file, number, error)
            if raw_id is not None:
                if raw_id in first_use:
                    self.add(
                        file,
                        number,
                        "id",
                        "duplicate_id",
                        f"{raw_id} is already used on line {first_use[raw_id]}",
                    )
                else:
                    first_use[raw_id] = number
            lines.append(_Line(number, raw_id, document))
        return lines

    def references(self, claims: list[_Line], results: list[_Line] | None) -> None:
        """Check that evidence ids refer to lines that exist.

        The ids of lines that are themselves invalid still count, so that a
        bad line is reported once and not again by every claim that cites it.
        """
        claim_ids = {line.raw_id for line in claims if line.raw_id is not None}
        result_ids = None if results is None else {line.raw_id for line in results if line.raw_id}
        for line in claims:
            if not isinstance(line.document, ClaimLedgerEntry):
                continue
            for position, entry in enumerate(line.document.evidence):
                field = f"evidence.{position}.id"
                if isinstance(entry, ResultRecordEvidence):
                    if result_ids is not None and entry.id not in result_ids:
                        self.add(
                            CLAIM_LEDGER_FILE,
                            line.number,
                            field,
                            "unknown_reference",
                            f"{entry.id} is not a result record in {RESULTS_FILE}",
                        )
                elif isinstance(entry, ClaimEvidence) and entry.id not in claim_ids:
                    self.add(
                        CLAIM_LEDGER_FILE,
                        line.number,
                        field,
                        "unknown_reference",
                        f"{entry.id} is not a claim in {CLAIM_LEDGER_FILE}",
                    )

    def sidecars(self) -> None:
        for path in self.entries(META_DIRECTORY):
            file = self.relative(path)
            if path.is_dir() or path.suffix != ".json":
                self.add(
                    file,
                    None,
                    DOCUMENT_FIELD,
                    "unexpected_file",
                    "only metadata sidecars, named <artifact_id>.json, belong here",
                )
                continue
            sidecar = self.document(ArtifactMetadata, file)
            if sidecar is not None and path.stem != sidecar.artifact_id:
                self.add(
                    file,
                    None,
                    "artifact_id",
                    "name_mismatch",
                    f"the file is named {path.name} but describes {sidecar.artifact_id}",
                )

    def sources(self) -> None:
        for path in self.entries(SOURCES_DIRECTORY):
            # Other files hold the stored text of the sources.
            if path.is_file() and path.suffix == ".json":
                self.document(SourceRecord, self.relative(path))

    def runs(self) -> None:
        for directory in self.entries(RUNS_DIRECTORY):
            path = directory / MANIFEST_FILE
            # A run that has not ended has no manifest yet.
            if not directory.is_dir() or not path.is_file():
                continue
            file = self.relative(path)
            manifest = self.document(RunManifest, file)
            if manifest is not None and manifest.run_id != directory.name:
                self.add(
                    file,
                    None,
                    "run_id",
                    "name_mismatch",
                    f"the manifest is in {RUNS_DIRECTORY}/{directory.name}/ "
                    f"but describes run {manifest.run_id}",
                )

    def approvals(self) -> None:
        requests: dict[str, ApprovalRequest | None] = {}
        responses: list[tuple[str, str, ApprovalResponse | None]] = []
        for path in self.entries(APPROVALS_DIRECTORY):
            file = self.relative(path)
            match = _APPROVAL_FILE.match(path.name)
            if path.is_dir() or match is None:
                self.add(
                    file,
                    None,
                    DOCUMENT_FIELD,
                    "unexpected_file",
                    "only <approval_id>.request.json and <approval_id>.response.json belong here",
                )
                continue
            named = match.group("id")
            if match.group("kind") == "request":
                request = self.document(ApprovalRequest, file)
                requests[named] = request
                self.check_name(file, named, request)
            else:
                response = self.document(ApprovalResponse, file)
                responses.append((file, named, response))
                self.check_name(file, named, response)
        for file, named, response in responses:
            if named not in requests:
                self.add(
                    file,
                    None,
                    DOCUMENT_FIELD,
                    "request_missing",
                    f"there is no request {APPROVALS_DIRECTORY}/{named}.request.json "
                    "for this response",
                )
                continue
            request = requests[named]
            if request is not None and response is not None:
                try:
                    check_response_matches_request(request, response, file)
                except ContractValidationError as error:
                    self.add_error(file, None, error)

    def check_name(
        self, file: str, named: str, document: ApprovalRequest | ApprovalResponse | None
    ) -> None:
        if document is not None and document.approval_id != named:
            self.add(
                file,
                None,
                "approval_id",
                "name_mismatch",
                f"the file is named for {named} but holds {document.approval_id}",
            )

    def entries(self, directory: str) -> Iterator[Path]:
        """Yield the entries of a project directory in name order, without `.gitkeep`."""
        path = self.project / directory
        if not path.is_dir():
            return
        for entry in sorted(path.iterdir()):
            if entry.name != GITKEEP_FILE:
                yield entry


def validate_project(directory: Path) -> ValidationReport:
    """Validate every contract file of a project and report every problem.

    Nothing in the project is changed. Paths in the report are relative to
    the project directory.
    """
    validator = _Validator(directory)
    if not directory.is_dir():
        validator.add(
            ".",
            None,
            DOCUMENT_FIELD,
            "not_a_directory",
            "the project directory does not exist or is not a directory",
        )
        return _report(validator)
    validator.config()
    validator.events()
    claims = validator.lines(ClaimLedgerEntry, CLAIM_LEDGER_FILE)
    results = validator.lines(ResultRecord, RESULTS_FILE)
    if claims is not None:
        validator.references(claims, results)
    validator.sidecars()
    validator.sources()
    validator.runs()
    validator.approvals()
    return _report(validator)


def _report(validator: _Validator) -> ValidationReport:
    return ValidationReport(tuple(validator.problems), validator.files_checked)
