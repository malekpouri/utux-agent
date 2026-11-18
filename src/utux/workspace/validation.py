"""Validation of every contract file of a project.

`validate_project` reads every contract file of a project, checks it
against its schema, and checks the rules that span lines or files: the log
starts with `project_created` and every parent exists; ids are unique within
`claims.jsonl`, `results.jsonl` and the source records; evidence ids refer to
existing lines and source records; every result's run has a manifest; file
names match the ids they hold; sidecar ids are unique, their inputs have
sidecars, and the current version of each path matches the file's content
hash; and an approval response matches its request.
It reports every problem it finds, not only the first, and changes nothing.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from utux.errors import DOCUMENT_FIELD, ContractValidationError, HashingError
from utux.events.log import FRAGMENT_SUFFIX, fragment_files
from utux.schemas.approval import (
    ApprovalRequest,
    ApprovalResponse,
    check_response_matches_request,
)
from utux.schemas.artifact_metadata import ArtifactMetadata
from utux.schemas.base import ContractDocument
from utux.schemas.claim_ledger import (
    ClaimEvidence,
    ClaimLedgerEntry,
    ResultRecordEvidence,
    SourceEvidence,
)
from utux.schemas.event import Event, EventType, event_number, format_event_id
from utux.schemas.json_io import parse_json
from utux.schemas.project_config import ProjectConfig
from utux.schemas.result_record import ResultRecord
from utux.schemas.run_manifest import RunManifest
from utux.schemas.source_record import SourceRecord
from utux.schemas.yaml_io import parse_yaml
from utux.workspace.hashing import hash_bytes, hash_file
from utux.workspace.layout import (
    CLAIM_LEDGER_FILE,
    CONFIG_FILE,
    EVENT_LOG_FILE,
    GITKEEP_FILE,
    RESULTS_FILE,
    hash_project_directory,
)

REPORT_SCHEMA_VERSION = 1
META_DIRECTORY = ".utux/meta"
SOURCES_DIRECTORY = "sources"
RUNS_DIRECTORY = "runs"
APPROVALS_DIRECTORY = "approvals"
MANIFEST_FILE = "manifest.json"

_FRAGMENT_NAME = re.compile(re.escape(EVENT_LOG_FILE + FRAGMENT_SUFFIX) + r"[^/\\]+")
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
        # (line, data) of every valid log_repaired event.
        self.repairs: list[tuple[int, dict[str, object]]] = []

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
        # Ids of earlier lines, also of invalid ones, so a bad line is reported once.
        seen: set[str] = set()
        with path.open("rb") as stream:
            # Read line by line, so a long log is never held in memory.
            for number, raw in enumerate(stream, start=1):
                if not raw.endswith(b"\n"):
                    self.add(
                        EVENT_LOG_FILE,
                        number,
                        DOCUMENT_FIELD,
                        "incomplete_line",
                        "the line is incomplete; a write to the log was interrupted; "
                        "run utux log repair",
                    )
                    continue
                text = raw.decode("utf-8", errors="replace")
                earlier = set(seen)
                try:
                    data = parse_json(text, EVENT_LOG_FILE)
                    if isinstance(data, dict) and isinstance(data.get("event_id"), str):
                        seen.add(data["event_id"])
                    event = Event.validate_document(data, EVENT_LOG_FILE)
                except ContractValidationError as error:
                    self.add_error(EVENT_LOG_FILE, number, error)
                    continue
                if number == 1 and event.type is not EventType.PROJECT_CREATED:
                    self.add(
                        EVENT_LOG_FILE,
                        number,
                        "type",
                        "first_event_not_project_created",
                        "the first event of the log must be project_created, "
                        f"not {event.type.value}",
                    )
                if event.type is EventType.LOG_REPAIRED:
                    self.repairs.append((number, dict(event.data)))
                if event.parent_id is not None and event.parent_id not in earlier:
                    self.add(
                        EVENT_LOG_FILE,
                        number,
                        "parent_id",
                        "unknown_reference",
                        f"{event.parent_id} is not an event in {EVENT_LOG_FILE}",
                    )
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
        # JSON Lines ends a line at "\n" only. str.splitlines() would also break
        # at characters such as U+2028 and U+0085, which may appear in text.
        parts = text.split("\n")
        if parts[-1] == "":
            parts.pop()
        for number, content in enumerate(parts, start=1):
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

    def references(
        self, claims: list[_Line], results: list[_Line] | None, source_ids: set[str]
    ) -> None:
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
                elif isinstance(entry, SourceEvidence):
                    if entry.source_id not in source_ids:
                        self.add(
                            CLAIM_LEDGER_FILE,
                            line.number,
                            f"evidence.{position}.source_id",
                            "unknown_reference",
                            f"{entry.source_id} has no source record in {SOURCES_DIRECTORY}/",
                        )
                elif isinstance(entry, ClaimEvidence) and entry.id not in claim_ids:
                    self.add(
                        CLAIM_LEDGER_FILE,
                        line.number,
                        field,
                        "unknown_reference",
                        f"{entry.id} is not a claim in {CLAIM_LEDGER_FILE}",
                    )

    def result_runs(self, results: list[_Line]) -> None:
        """Check that every result record's run has a manifest."""
        for line in results:
            if not isinstance(line.document, ResultRecord):
                continue
            run_id = line.document.run_id
            manifest = f"{RUNS_DIRECTORY}/{run_id}/{MANIFEST_FILE}"
            # The manifest counts when it exists; whether it is valid is its own check.
            if not (self.project / manifest).is_file():
                self.add(
                    RESULTS_FILE,
                    line.number,
                    "run_id",
                    "unknown_reference",
                    f"{run_id} has no run manifest {manifest}",
                )

    def sidecars(self) -> None:
        """Check the sidecars, their ids and inputs, and each current version's file.

        The ids of sidecars that are themselves invalid still count, so that a
        bad sidecar is reported once and not again by every sidecar built
        from it.
        """
        first_use: dict[str, str] = {}
        valid: list[tuple[str, ArtifactMetadata]] = []
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
            text = self.read_text(file)
            if text is None:
                continue
            artifact_id: str | None = None
            sidecar: ArtifactMetadata | None = None
            try:
                data = parse_json(text, file)
                if isinstance(data, dict) and isinstance(data.get("artifact_id"), str):
                    artifact_id = data["artifact_id"]
                sidecar = ArtifactMetadata.validate_document(data, file)
            except ContractValidationError as error:
                self.add_error(file, None, error)
            duplicate = artifact_id is not None and artifact_id in first_use
            if artifact_id is not None:
                if duplicate:
                    self.add(
                        file,
                        None,
                        "artifact_id",
                        "duplicate_id",
                        f"{artifact_id} is already described by {first_use[artifact_id]}",
                    )
                else:
                    first_use[artifact_id] = file
            if sidecar is not None:
                # A duplicate is reported once, above, and takes no further part.
                if not duplicate:
                    valid.append((file, sidecar))
                if path.stem != sidecar.artifact_id:
                    self.add(
                        file,
                        None,
                        "artifact_id",
                        "name_mismatch",
                        f"the file is named {path.name} but describes {sidecar.artifact_id}",
                    )
        for file, sidecar in valid:
            for position, entry in enumerate(sidecar.input_artifacts):
                if entry not in first_use:
                    self.add(
                        file,
                        None,
                        f"input_artifacts.{position}",
                        "unknown_reference",
                        f"{entry} has no sidecar in {META_DIRECTORY}/",
                    )
        self.current_versions(valid)

    def current_versions(self, sidecars: list[tuple[str, ArtifactMetadata]]) -> None:
        """Check the current version of each path against the file it describes."""
        by_path: dict[str, list[tuple[int, str, ArtifactMetadata]]] = {}
        for file, sidecar in sidecars:
            version = int(sidecar.artifact_id.rsplit("-v", 1)[1])
            by_path.setdefault(sidecar.path, []).append((version, file, sidecar))
        for versions in by_path.values():
            highest = max(version for version, _, _ in versions)
            current = [(file, sidecar) for version, file, sidecar in versions if version == highest]
            first_file, first = current[0]
            if len(current) > 1:
                # Without one current version there is nothing to check the file against.
                for file, sidecar in current[1:]:
                    self.add(
                        file,
                        None,
                        "artifact_id",
                        "duplicate_version",
                        f"{first.artifact_id} in {first_file} is also version {highest} "
                        f"of {sidecar.path}; the current version is not defined",
                    )
                continue
            self.check_content(first_file, first)

    def check_content(self, file: str, sidecar: ArtifactMetadata) -> None:
        """Compare a sidecar's content hash with the file or directory at its path."""
        # The path comes from a file of the project; it is checked to stay inside
        # the project, symbolic links resolved, before anything is read by it.
        root = self.project.resolve()
        target = self.project / sidecar.path
        resolved = target.resolve()
        if not resolved.is_relative_to(root):
            self.add(
                file,
                None,
                "path",
                "path_outside_project",
                f"{sidecar.path} leads outside the project directory; it is not read",
            )
            return
        if not resolved.exists():
            self.add(file, None, "path", "missing_file", f"{sidecar.path} does not exist")
            return
        try:
            actual = hash_project_directory(resolved) if resolved.is_dir() else hash_file(resolved)
        except HashingError as error:
            self.add(file, None, "path", "unhashable", f"{sidecar.path} cannot be hashed: {error}")
            return
        if actual != sidecar.content_hash:
            self.add(
                file,
                None,
                "content_hash",
                "content_hash_mismatch",
                f"{sidecar.path} has the hash {actual}, not {sidecar.content_hash}; "
                "the file changed after this version was recorded",
            )

    def sources(self) -> set[str]:
        """Check the source records and return their source ids.

        The ids of records that are themselves invalid still count, so that a
        bad record is reported once.
        """
        first_use: dict[str, str] = {}
        for path in self.entries(SOURCES_DIRECTORY):
            # Other files hold the stored text of the sources.
            if not (path.is_file() and path.suffix == ".json"):
                continue
            file = self.relative(path)
            text = self.read_text(file)
            if text is None:
                continue
            source_id: str | None = None
            try:
                data = parse_json(text, file)
                if isinstance(data, dict) and isinstance(data.get("source_id"), str):
                    source_id = data["source_id"]
                SourceRecord.validate_document(data, file)
            except ContractValidationError as error:
                self.add_error(file, None, error)
            if source_id is None:
                continue
            if source_id in first_use:
                self.add(
                    file,
                    None,
                    "source_id",
                    "duplicate_id",
                    f"{source_id} is already used by {first_use[source_id]}",
                )
            else:
                first_use[source_id] = file
        return set(first_use)

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

    def fragments(self) -> None:
        """Check fragment side files and `log_repaired` events against each other."""
        sides = fragment_files(self.project / EVENT_LOG_FILE)
        self.files_checked += len(sides)
        recorded: set[str] = set()
        for number, data in self.repairs:
            name = data["fragment_file"]
            # The name comes from the log; it must name a side file beside the
            # log before any file is opened by it.
            if not isinstance(name, str) or _FRAGMENT_NAME.fullmatch(name) is None:
                self.add(
                    EVENT_LOG_FILE,
                    number,
                    "data.fragment_file",
                    "invalid_fragment_file",
                    f"must be a file name {EVENT_LOG_FILE}{FRAGMENT_SUFFIX}<time> beside the log",
                )
                continue
            recorded.add(name)
            path = self.project / name
            if not path.is_file():
                self.add(
                    EVENT_LOG_FILE,
                    number,
                    "data.fragment_file",
                    "missing_fragment_file",
                    f"{name} does not exist",
                )
                continue
            try:
                content = path.read_bytes()
            except OSError as error:
                self.add(
                    name,
                    None,
                    DOCUMENT_FIELD,
                    "unreadable",
                    f"the file cannot be read: {error.strerror}",
                )
                continue
            if len(content) != data["fragment_bytes"]:
                self.add(
                    EVENT_LOG_FILE,
                    number,
                    "data.fragment_bytes",
                    "fragment_mismatch",
                    f"{name} has {len(content)} bytes, not {data['fragment_bytes']}",
                )
            if hash_bytes(content) != data["fragment_hash"]:
                self.add(
                    EVENT_LOG_FILE,
                    number,
                    "data.fragment_hash",
                    "fragment_mismatch",
                    f"{name} has the hash {hash_bytes(content)}, not {data['fragment_hash']}",
                )
        for side in sides:
            if side.name not in recorded:
                self.add(
                    side.name,
                    None,
                    DOCUMENT_FIELD,
                    "unrecorded_fragment",
                    f"no log_repaired event in {EVENT_LOG_FILE} records this fragment; "
                    "run utux log repair",
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
    validator.fragments()
    claims = validator.lines(ClaimLedgerEntry, CLAIM_LEDGER_FILE)
    results = validator.lines(ResultRecord, RESULTS_FILE)
    source_ids = validator.sources()
    if claims is not None:
        validator.references(claims, results, source_ids)
    if results is not None:
        validator.result_runs(results)
    validator.sidecars()
    validator.runs()
    validator.approvals()
    return _report(validator)


def _report(validator: _Validator) -> ValidationReport:
    return ValidationReport(tuple(validator.problems), validator.files_checked)
