"""Export of the contract schemas as JSON Schema files.

One file is written per contract, so that other tools can validate project
files without utux. A JSON Schema states the fields, their types and the
closed sets. It does not state the rules between fields, such as "a verified
claim needs evidence"; those are checked only by utux itself.
"""

import json
from pathlib import Path

from utux.errors import AtomicWriteError, SchemaExportError
from utux.schemas.approval import ApprovalRequest, ApprovalResponse
from utux.schemas.artifact_metadata import ArtifactMetadata
from utux.schemas.base import ContractDocument
from utux.schemas.claim_ledger import ClaimLedgerEntry
from utux.schemas.event import Event
from utux.schemas.project_config import ProjectConfig
from utux.schemas.result_record import ResultRecord
from utux.schemas.run_manifest import RunManifest
from utux.schemas.source_record import SourceRecord
from utux.workspace.atomic import atomic_write_text

JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

NOT_SUFFICIENT = (
    "utux applies further rules between fields; "
    "passing this schema is necessary but not sufficient."
)

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
        own = schema.get("description")
        schema["description"] = f"{own}\n\n{NOT_SUFFICIENT}" if own else NOT_SUFFICIENT
        text = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        path = directory / f"{name}.schema.json"
        try:
            atomic_write_text(path, text)
        except AtomicWriteError as error:
            raise SchemaExportError(str(error)) from error
        written.append(path)
    return tuple(written)
