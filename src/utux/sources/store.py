"""The stored sources of a project, in `sources/` (task M2-03).

Each source has a record, `sources/<stem>.json`, and, when its text is
stored, the text beside it, `sources/<stem>.txt`. The stem is the source id
lowercased, with every character other than `a`-`z` and `0`-`9` replaced by
`-`, cut to 60 characters, then `-` and the first eight hexadecimal digits of
the SHA-256 hash of the source id (rule 17 of `docs/plan/M2.md`). The record
keeps the real source id.

Passages are computed from the stored text by the shared splitter, never
stored. A source whose licence does not permit storing its text is recorded
with metadata only; its text is `no_text` (RFC-001, S2).
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from utux.errors import SourceStoreError
from utux.schemas.source_record import SourceRecord, load_source_record
from utux.sources.passages import Passage, split_passages
from utux.workspace.atomic import atomic_write_text
from utux.workspace.hashing import hash_bytes

SOURCES_DIRECTORY = "sources"
NO_TEXT = "no_text"
"""The reason a source has no text to check a claim against (RFC-001, S2)."""

_NOT_SLUG = re.compile(r"[^a-z0-9]")
_SLUG_LENGTH = 60


def source_file_stem(source_id: str) -> str:
    """The file name of a source's record and text, without the suffix."""
    slug = _NOT_SLUG.sub("-", source_id.lower())[:_SLUG_LENGTH]
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def _paths(project: Path, source_id: str) -> tuple[Path, Path]:
    stem = source_file_stem(source_id)
    directory = project / SOURCES_DIRECTORY
    return directory / f"{stem}.json", directory / f"{stem}.txt"


@dataclass(frozen=True)
class StoredSource:
    """A source's record and its stored text, if any."""

    record: SourceRecord
    text: str | None


@dataclass(frozen=True)
class SourceText:
    """The text to check a claim against, or the reason there is none."""

    text: str | None
    reason: str | None


def write_source(project: Path, record: SourceRecord, text: str | None) -> None:
    """Store a source: its text first, then its record.

    Raises:
        SourceStoreError: Text for a source whose licence does not permit
            storing it; a text whose hash is not the record's; or a record
            that names a stored text without one. Nothing is written.
    """
    record_path, text_path = _paths(project, record.source_id)
    if text is not None and not record.storage_permitted:
        raise SourceStoreError(
            f"the licence of {record.source_id} does not permit storing its text; record it "
            "with metadata only"
        )
    if text is None and record.stored_text is not None:
        raise SourceStoreError(
            f"the record of {record.source_id} names a stored {record.stored_text.value}, "
            "but no text is given"
        )
    if text is not None:
        actual = hash_bytes(text.encode("utf-8"))
        if actual != record.text_hash:
            raise SourceStoreError(
                f"the text of {record.source_id} has the hash {actual}, not the record's "
                f"{record.text_hash}"
            )
        # The text first, so that a record never names a text that is not there.
        atomic_write_text(text_path, text)
    atomic_write_text(record_path, record.to_json())


def read_source(project: Path, source_id: str) -> StoredSource:
    """Read a source's record and its text, checking the text against its hash.

    Raises:
        SourceStoreError: The source is not stored, its text is missing, or
            the text's hash is not the record's.
        ContractValidationError: The record is not valid.
    """
    record_path, text_path = _paths(project, source_id)
    if not record_path.is_file():
        raise SourceStoreError(f"{source_id} is not stored in {SOURCES_DIRECTORY}/")
    record = load_source_record(record_path)
    if record.source_id != source_id:
        raise SourceStoreError(
            f"{record_path.name} holds the record of {record.source_id}, not of {source_id}"
        )
    if record.stored_text is None:
        return StoredSource(record, None)
    if not text_path.is_file():
        raise SourceStoreError(f"the stored text of {source_id} is missing: {text_path.name}")
    text = text_path.read_text(encoding="utf-8")
    actual = hash_bytes(text.encode("utf-8"))
    if actual != record.text_hash:
        raise SourceStoreError(
            f"the stored text of {source_id} has the hash {actual}, not the record's "
            f"{record.text_hash}; it changed after it was stored"
        )
    return StoredSource(record, text)


def source_text(project: Path, source_id: str) -> SourceText:
    """The text to check a source's claims against, or `no_text`."""
    stored = read_source(project, source_id)
    if stored.text is None:
        return SourceText(None, NO_TEXT)
    return SourceText(stored.text, None)


def stored_passages(project: Path, source_id: str) -> tuple[Passage, ...]:
    """The passages of a source's stored text, computed by the shared splitter."""
    stored = read_source(project, source_id)
    if stored.text is None or stored.record.stored_text is None:
        return ()
    return split_passages(stored.text, stored.record.stored_text)
