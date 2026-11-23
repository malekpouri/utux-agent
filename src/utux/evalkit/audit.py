"""The maintainer's blind audit of gold v0 (M0-15c, gold v0 strategy, section 8).

`export_audit` draws 30 items by a fixed seed: 20 of the model-written types
(`confirmation: model_check`) and 10 imported items. It writes them as a
sheet with the claim, the evidence and an empty status column, and no item
id, origin, constructed label or flag. A separate key maps each row to its
item; the maintainer does not need to open it.

`score_audit` reads the filled sheet and computes Cohen's kappa between the
maintainer's statuses and the constructed ones. A kappa below 0.6, or one
that cannot be computed, is flagged: it triggers a review of the mapping. A
perturbation the maintainer agrees with becomes `confirmation: audit`, with
the maintainer's pseudonymous id. No label is ever changed.
"""

import csv
import io
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from utux.errors import GoldSetError
from utux.evalkit.agreement import cohens_kappa
from utux.evalkit.gold import Confirmation, GoldItem, GoldStatus, Origin, PerturbationRecord
from utux.evalkit.perturb import evidence_text

AUDIT_COLUMNS = ("row", "claim", "evidence", "status")
KAPPA_FLOOR = 0.6
"""Below this kappa the label mapping is reviewed (maintainer, 2026-11-22)."""
MODEL_WRITTEN = 20
IMPORTED = 10


def _confirmation(item: GoldItem) -> Confirmation | None:
    return item.hidden.confirmation if isinstance(item.hidden, PerturbationRecord) else None


def export_audit(
    items: Sequence[GoldItem],
    texts: Mapping[str, str],
    *,
    seed: int,
    model_written: int = MODEL_WRITTEN,
    imported: int = IMPORTED,
) -> tuple[str, dict[str, str]]:
    """The blind sheet, as CSV, and the key from row to item id.

    Raises:
        GoldSetError: There are too few items of either kind.
    """
    checked = sorted(
        (i for i in items if _confirmation(i) is Confirmation.MODEL_CHECK), key=lambda i: i.item_id
    )
    public = sorted((i for i in items if i.origin is Origin.PUBLIC), key=lambda i: i.item_id)
    if len(checked) < model_written:
        raise GoldSetError(
            f"only {len(checked)} items have confirmation model_check; the audit needs "
            f"{model_written}"
        )
    if len(public) < imported:
        raise GoldSetError(f"only {len(public)} imported items; the audit needs {imported}")
    rng = random.Random(seed)
    picked = rng.sample(checked, model_written) + rng.sample(public, imported)
    rng.shuffle(picked)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(AUDIT_COLUMNS), lineterminator="\n")
    writer.writeheader()
    key: dict[str, str] = {}
    for number, item in enumerate(picked, start=1):
        row = f"r{number:02d}"
        claim = item.claims[0]
        evidence = "\n---\n".join(evidence_text(pair, texts) for pair in claim.pairs)
        writer.writerow({"row": row, "claim": item.text_unit, "evidence": evidence, "status": ""})
        key[row] = item.item_id
    return out.getvalue(), key


@dataclass(frozen=True)
class AuditResult:
    """The audit's agreement, and the items with the confirmed ones upgraded."""

    kappa: float | None
    agreed: int
    disagreed: int
    below_floor: bool
    upgraded: tuple[str, ...]
    items: tuple[GoldItem, ...]

    def report(self) -> dict[str, object]:
        """Counts and kappa only."""
        return {
            "rows": self.agreed + self.disagreed,
            "agreed": self.agreed,
            "disagreed": self.disagreed,
            "cohens_kappa": self.kappa,
            "kappa_floor": KAPPA_FLOOR,
            "below_floor": self.below_floor,
            "upgraded_to_audit": len(self.upgraded),
        }


def score_audit(
    items: Sequence[GoldItem], key: Mapping[str, str], sheet: str, *, annotator: str
) -> AuditResult:
    """Score the filled sheet against the constructed labels.

    Raises:
        GoldSetError: The sheet does not match the key, or a status is
            missing or not one of the four statuses.
    """
    reader = csv.DictReader(io.StringIO(sheet))
    if tuple(reader.fieldnames or ()) != AUDIT_COLUMNS:
        raise GoldSetError(f"the sheet's columns must be {', '.join(AUDIT_COLUMNS)}")
    answers: dict[str, str] = {}
    statuses = {status.value for status in GoldStatus}
    for row in reader:
        answer = (row.get("status") or "").strip().lower()
        if answer not in statuses:
            raise GoldSetError(
                f"row {row.get('row')}: the status must be one of {', '.join(sorted(statuses))}"
            )
        answers[str(row.get("row"))] = answer
    if set(answers) != set(key):
        raise GoldSetError("the sheet's rows do not match the key")
    by_id = {item.item_id: item for item in items}
    pairs = [(answers[row], by_id[item_id].claims[0].status.value) for row, item_id in key.items()]
    kappa = cohens_kappa(pairs, sorted(statuses))
    confirmed = {
        item_id
        for row, item_id in key.items()
        if answers[row] == by_id[item_id].claims[0].status.value
        and _confirmation(by_id[item_id]) is Confirmation.MODEL_CHECK
    }
    upgraded_items = []
    for item in items:
        if item.item_id in confirmed and isinstance(item.hidden, PerturbationRecord):
            hidden = PerturbationRecord.model_validate(
                {
                    **item.hidden.model_dump(),
                    "confirmation": Confirmation.AUDIT,
                    "confirmed_by": annotator,
                }
            )
            item = item.model_copy(update={"hidden": hidden})
        upgraded_items.append(item)
    agreed = sum(1 for mine, theirs in pairs if mine == theirs)
    return AuditResult(
        kappa=kappa,
        agreed=agreed,
        disagreed=len(pairs) - agreed,
        below_floor=kappa is None or kappa < KAPPA_FLOOR,
        upgraded=tuple(sorted(confirmed)),
        items=tuple(upgraded_items),
    )
