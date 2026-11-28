"""The citation existence items of gold v0 (M0-15c, RFC-002 section 3).

Real references come from the titles of the SciFact corpus, found by
OpenAlex title search. A title is accepted only when exactly one result has
the identical normalised title (`utux.verification.existence.normalise`);
otherwise it is dropped and counted (maintainer, PR #59 review). The search
makes network calls, so the command that runs it is the maintainer's.

Each real reference gives two items: the reference as found, which exists,
and one altered copy, which does not, for one reason that follows from the
alteration. The alterations turn in a fixed order: title, first author, year.

- **Title:** another record's title, with a title similarity below 0.9.
- **First author:** another record's family name, not found as whole words
  in this record's first author.
- **Year:** three years later, beyond the tolerance of one.

The cited family name of a real reference is the last word of the first
author's display name. It is a rule for building the reference; the
existence check itself never splits a display name.
"""

import json
import random
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Protocol, Self

from pydantic import Field, StrictBool, StrictInt, model_validator
from pydantic_core import PydanticCustomError

from utux.errors import LiteratureSourceError
from utux.evalkit.gold import GoldSplit, GoldVersion
from utux.interfaces.literature_source import WorkMetadata
from utux.schemas.base import ContractDocument, ContractPart
from utux.schemas.common import NonEmptyText
from utux.schemas.source_record import Author
from utux.verification.existence import (
    TITLE_SIMILARITY,
    YEAR_TOLERANCE,
    ExistenceReason,
    Reference,
    first_author_matches,
    normalise,
    title_similarity,
)

SEARCH_LIMIT = 5
YEAR_SHIFT = 3
LICENCE = "CC BY-NC 2.0"
"""SciFact's titles carry its licence (maintainer, 2026-11-22)."""
DEV_SHARE = 0.3

ExistenceItemId = Annotated[str, Field(pattern=r"^E[0-9]{4,}$", strict=True)]


class Construction(StrEnum):
    """How an existence item was made."""

    REAL = "real"
    TITLE_ALTERED = "title_altered"
    AUTHOR_ALTERED = "author_altered"
    YEAR_ALTERED = "year_altered"


EXPECTED_REASON = {
    Construction.TITLE_ALTERED: ExistenceReason.TITLE_MISMATCH,
    Construction.AUTHOR_ALTERED: ExistenceReason.AUTHOR_MISMATCH,
    Construction.YEAR_ALTERED: ExistenceReason.YEAR_MISMATCH,
}
_ROTATION = (Construction.TITLE_ALTERED, Construction.AUTHOR_ALTERED, Construction.YEAR_ALTERED)


class Searcher(Protocol):
    """What the search needs of a literature source."""

    def search(self, query: str, limit: int) -> tuple[WorkMetadata, ...]:
        """Works for a query."""
        ...


@dataclass(frozen=True)
class RealReference:
    """A SciFact corpus document found by its exact title."""

    doc_id: str
    identifier: str
    title: str
    first_author_display: str
    first_author_family: str
    year: int


class CitedReference(ContractPart):
    """A bibliography entry as an existence item cites it."""

    key: NonEmptyText
    identifier: NonEmptyText
    title: NonEmptyText
    first_author_family: NonEmptyText
    year: StrictInt

    def as_reference(self) -> Reference:
        """The entry as the existence check takes it."""
        return Reference(self.key, self.identifier, self.title, self.first_author_family, self.year)


class ExistenceProvenance(ContractPart):
    """Where the real record came from."""

    dataset: NonEmptyText
    original_id: NonEmptyText
    licence: NonEmptyText
    resolved_by: NonEmptyText
    first_author_display: NonEmptyText


class ExistenceItem(ContractDocument):
    """One citation existence item: a reference and whether it exists, by construction."""

    SCHEMA_VERSION: ClassVar[int] = 1

    item_id: ExistenceItemId
    gold_version: GoldVersion
    split: GoldSplit | None
    construction: Construction
    reference: CitedReference
    expected_exists: StrictBool
    expected_reasons: tuple[ExistenceReason, ...]
    source_item: ExistenceItemId | None
    provenance: ExistenceProvenance

    @model_validator(mode="after")
    def _parts_agree(self) -> Self:
        real = self.construction is Construction.REAL
        reasons = () if real else (EXPECTED_REASON[self.construction],)
        if (
            self.expected_exists is not real
            or self.expected_reasons != reasons
            or (self.source_item is None) is not real
        ):
            raise PydanticCustomError(
                "construction_mismatch",
                "a real item exists with no reasons and no source item; an altered one does "
                "not exist, has its construction's reason and names its real item",
            )
        return self

    def to_json_line(self) -> str:
        """The item as one line of JSON that ends with a newline."""
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False) + "\n"


def scifact_titles(scifact: Path, doc_ids: Iterable[str]) -> dict[str, str]:
    """The titles of these documents in the SciFact release's `data/corpus.jsonl`."""
    wanted = set(doc_ids)
    titles: dict[str, str] = {}
    for line in (scifact / "data" / "corpus.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or str(row.get("doc_id")) not in wanted:
            continue
        title = row.get("title")
        if isinstance(title, str) and title.strip():
            titles[str(row["doc_id"])] = " ".join(title.split())
    return dict(sorted(titles.items()))


def _first_author(work: WorkMetadata) -> tuple[str, str] | None:
    if not work.authors:
        return None
    author: Author = work.authors[0]
    display = author.display_name or " ".join(p for p in (author.given, author.family) if p)
    words = display.split()
    if not words:
        return None
    return display, author.family or words[-1]


def find_real_references(
    titles: Mapping[str, str], search: Searcher, *, limit: int = SEARCH_LIMIT
) -> tuple[tuple[RealReference, ...], Counter[str]]:
    """Search each title; keep it only when exactly one result has the identical title.

    Returns the real references in document order, and the drops by reason.
    """
    found: list[RealReference] = []
    dropped: Counter[str] = Counter()
    for doc_id, title in sorted(titles.items()):
        try:
            works = search.search(title, limit)
        except LiteratureSourceError:
            dropped["search_failed"] += 1
            continue
        same = [w for w in works if w.title is not None and normalise(w.title) == normalise(title)]
        if not same:
            dropped["no_identical_title"] += 1
            continue
        if len(same) > 1:
            dropped["ambiguous_title"] += 1
            continue
        work = same[0]
        author = _first_author(work)
        if author is None:
            dropped["missing_author"] += 1
            continue
        if work.year is None:
            dropped["missing_year"] += 1
            continue
        found.append(RealReference(doc_id, work.identifier, title, author[0], author[1], work.year))
    return tuple(found), dropped


def _item(
    number: int,
    construction: Construction,
    record: RealReference,
    reference: CitedReference,
    source_item: str | None,
) -> ExistenceItem:
    real = construction is Construction.REAL
    return ExistenceItem(
        schema_version=ExistenceItem.SCHEMA_VERSION,
        item_id=f"E{number:05d}",
        gold_version="0.1",
        split=None,
        construction=construction,
        reference=reference,
        expected_exists=real,
        expected_reasons=() if real else (EXPECTED_REASON[construction],),
        source_item=source_item,
        provenance=ExistenceProvenance(
            dataset="scifact",
            original_id=record.doc_id,
            licence=LICENCE,
            resolved_by="openalex",
            first_author_display=record.first_author_display,
        ),
    )


def _altered(
    record: RealReference,
    construction: Construction,
    others: Sequence[RealReference],
    reference: CitedReference,
) -> CitedReference | None:
    if construction is Construction.YEAR_ALTERED:
        year = record.year + YEAR_SHIFT
        assert abs(year - record.year) > YEAR_TOLERANCE
        return reference.model_copy(update={"year": year})
    for other in others:
        if construction is Construction.TITLE_ALTERED:
            if title_similarity(other.title, record.title) < TITLE_SIMILARITY:
                return reference.model_copy(update={"title": other.title})
        elif not first_author_matches(
            other.first_author_family, Author(display_name=record.first_author_display)
        ):
            return reference.model_copy(update={"first_author_family": other.first_author_family})
    return None


def build_existence_items(
    records: Sequence[RealReference], *, seed: int, dev_share: float = DEV_SHARE
) -> tuple[ExistenceItem, ...]:
    """A real item and one altered copy per record, split by record.

    A record whose turn of alteration finds no other record that changes it
    enough gives only its real item.
    """
    ordered = sorted(records, key=lambda r: r.doc_id)
    items: list[ExistenceItem] = []
    groups: list[list[ExistenceItem]] = []
    for index, record in enumerate(ordered):
        reference = CitedReference(
            key=f"scifact{record.doc_id}",
            identifier=record.identifier,
            title=record.title,
            first_author_family=record.first_author_family,
            year=record.year,
        )
        real = _item(len(items) + 1, Construction.REAL, record, reference, None)
        group = [real]
        construction = _ROTATION[index % len(_ROTATION)]
        others = ordered[index + 1 :] + ordered[:index]
        changed = _altered(record, construction, others, reference)
        if changed is not None:
            group.append(_item(len(items) + 2, construction, record, changed, real.item_id))
        items += group
        groups.append(group)
    rng = random.Random(seed)
    rng.shuffle(groups)
    target = round(dev_share * len(items))
    in_dev = 0
    splits: dict[str, GoldSplit] = {}
    for group in groups:
        split = GoldSplit.DEV if in_dev + len(group) <= target else GoldSplit.TEST
        in_dev += len(group) if split is GoldSplit.DEV else 0
        for item in group:
            splits[item.item_id] = split
    return tuple(item.model_copy(update={"split": splits[item.item_id]}) for item in items)
