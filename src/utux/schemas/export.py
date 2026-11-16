"""Export of the contract schemas as JSON Schema files.

One file is written per contract, so that other tools can validate project
files without utux. A JSON Schema states the fields, their types and the
closed sets. It does not state the rules between fields, such as "a verified
claim needs evidence"; those are checked only by utux itself.
"""

import json
import os
import tempfile
from pathlib import Path

from utux.errors import SchemaExportError
from utux.schemas.approval import ApprovalRequest, ApprovalResponse
from utux.schemas.artifact_metadata import ArtifactMetadata
from utux.schemas.base import ContractDocument
from utux.schemas.claim_ledger import ClaimLedgerEntry
from utux.schemas.event import Event
from utux.schemas.project_config import ProjectConfig
from utux.schemas.result_record import ResultRecord
from utux.schemas.run_manifest import RunManifest
from utux.schemas.source_record import SourceRecord

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

CONTRACTS: dict[str, type[ContractDocument]] = {
    "project_config": ProjectConfig,
    "artifact_metadata": ArtifactMetadata,
    "event": Event,
    "claim_ledger_entry": ClaimLedgerEntry,
    "result_record": ResultRecord,
    "run_manifest": RunManifest,
    "approval_request": ApprovalRequest,
    "approval_response": ApprovalResponse,
    "source_record": SourceRecord,
}
"""Every file contract, by the name used for its schema file."""


def export_json_schemas(directory: Path) -> tuple[Path, ...]:
    """Write `<name>.schema.json` for every contract into a directory.

    The directory is created if it does not exist. Existing schema files are
    replaced; other files in the directory are left alone. The output is the
    same for the same version of utux.

    Returns:
        The files written, in the order of `CONTRACTS`.

    Raises:
        SchemaExportError: If the directory cannot be created or a file
            cannot be written.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise SchemaExportError(
            f"cannot use {directory} as a directory: {error.strerror}"
        ) from error
    written = []
    for name, model in CONTRACTS.items():
        schema = {"$schema": JSON_SCHEMA_DIALECT, **model.model_json_schema()}
        text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path = directory / f"{name}.schema.json"
        _replace_file(path, text)
        written.append(path)
    return tuple(written)


def _replace_file(path: Path, text: str) -> None:
    """Write a file through a temporary file in the same directory, then rename.

    A reader never sees a partly written schema. The shared atomic writer of
    the workspace package (task M0-07) will take the place of this function.
    """
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=".", suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as error:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
        raise SchemaExportError(f"cannot write {path}: {error.strerror}") from error
