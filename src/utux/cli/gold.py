"""`utux gold`: the commands of the gold-set tooling, thin over `utux.evalkit`.

They read and write the files of `docs/annotation-tooling.md`. They hold no
logic of their own and never write, suggest or change a label.
"""

import json
import os
import random
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer

from utux.errors import ContractValidationError, ModelAuthenticationError, UtuxError
from utux.evalkit.agreement import AgreementReport, ExtractionAgreement, LabelAgreement
from utux.evalkit.annotation import (
    ExtractionWork,
    LabellingWork,
    Phase,
    ReferenceClaims,
    disagreements_json,
    export_batch,
    extraction_agreement,
    labelling_agreement,
    load_adjudication,
    load_batch,
    load_pool,
    merge_extraction,
    merge_labelling,
    read_items,
    read_work,
    release_text,
    with_splits,
    write_annotation_page,
)
from utux.evalkit.audit import export_audit, score_audit
from utux.evalkit.existence_items import (
    build_existence_items,
    find_real_references,
    scifact_titles,
)
from utux.evalkit.gold import GoldItem, PublicDataset, check_release, read_gold_release
from utux.evalkit.model_perturb import (
    GEMINI_KEY_VARIABLE,
    CappedCaller,
    build_model_perturbations,
    gemini_provider,
)
from utux.evalkit.perturb import MAX_UNCITED, build_rule_perturbations
from utux.evalkit.public import (
    ensure_outside_git,
    import_public,
    load_imported,
    summarize,
    write_public_import,
)
from utux.evalkit.sample import DEV_SHARE as SAMPLE_DEV_SHARE
from utux.evalkit.sample import SampleSizes, sample_v0, select_imported
from utux.evalkit.splits import assign_splits, split_report
from utux.events.log import EventLog
from utux.schemas.project_config import DataPolicy
from utux.sources.calls import LoggedLiteratureSource
from utux.sources.openalex import OpenAlexSource
from utux.workspace.atomic import atomic_write_text
from utux.workspace.hashing import hash_file

gold_app = typer.Typer(
    help="Tooling for the gold set: pools, batches, work files, merges and releases."
)

DEV_SHARE = 0.3
"""The share of items in `dev` (RFC-002, section 6)."""


@gold_app.callback()
def gold_root() -> None:
    """Tooling for the gold set: pools, batches, work files, merges and releases."""


def _fail(error: UtuxError) -> typer.Exit:
    if isinstance(error, ContractValidationError):
        for problem in error.problems:
            typer.echo(
                f"error: {error.source}: {problem.field}: {problem.reason} ({problem.code})",
                err=True,
            )
    else:
        typer.echo(f"error: {error}", err=True)
    return typer.Exit(code=1)


def _count(number: int, word: str) -> str:
    return f"{number} {word}{'' if number == 1 else 's'}"


Pool = Annotated[Path, typer.Argument(help="The pool file.")]
SeedOption = Annotated[int, typer.Option("--seed", help="The seed of the split.")]
DevShare = Annotated[float, typer.Option("--dev-share", help="The share of items in dev.")]


@gold_app.command("pool-check")
def pool_check(pool: Pool) -> None:
    """Check a pool file and count its items, sources and passages."""
    try:
        loaded = load_pool(pool)
    except UtuxError as error:
        raise _fail(error) from error
    sources = [source for item in loaded.items for source in item.sources]
    passages = sum(len(source.passages) for source in sources)
    typer.echo(
        f"The pool is valid: {_count(len(loaded.items), 'item')}, "
        f"{_count(len(sources), 'source')}, {_count(passages, 'passage')}."
    )


@gold_app.command("batch")
def batch(
    pool: Pool,
    phase: Annotated[Phase, typer.Option("--phase", help="claim_extraction or labelling.")],
    annotator: Annotated[str, typer.Option("--annotator", help="The id, such as a03.")],
    batch_id: Annotated[str, typer.Option("--batch-id", help="The batch, such as b01.")],
    out: Annotated[Path, typer.Option("--out", help="The directory to write into.")],
    references: Annotated[
        Path | None,
        typer.Option("--references", help="The reference claims, for a labelling batch."),
    ] = None,
) -> None:
    """Write one annotator's batch, and the annotation page beside it."""
    try:
        loaded = load_pool(pool)
        claims = (
            None
            if references is None
            else ReferenceClaims.validate_document(
                json.loads(references.read_text(encoding="utf-8")), str(references)
            )
        )
        made = export_batch(loaded, phase, annotator, batch_id, references=claims)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"batch-{batch_id}-{annotator}-{phase.value}.json"
        atomic_write_text(path, made.to_json())
        page = write_annotation_page(out)
    except UtuxError as error:
        raise _fail(error) from error
    typer.echo(f"Wrote {path}")
    typer.echo(f"Wrote {page}")


@gold_app.command("import")
def import_work(
    batch_file: Annotated[Path, typer.Argument(help="The annotator's batch.")],
    work_file: Annotated[Path, typer.Argument(help="The work file the page exported.")],
) -> None:
    """Check a work file against its batch and count what it holds."""
    try:
        work = read_work(load_batch(batch_file), work_file)
    except UtuxError as error:
        raise _fail(error) from error
    claims = sum(len(item.claims) for item in work.items)
    flagged = sum(1 for item in work.items if item.flag is not None)
    typer.echo(
        f"The {work.phase.value} work of {work.annotator} on batch {work.batch_id} is valid: "
        f"{_count(len(work.items), 'item')}, {_count(claims, 'claim')}, "
        f"{flagged} flagged for the adjudicator."
    )


def _two_works(
    first_batch: Path, first_work: Path, second_batch: Path, second_work: Path
) -> tuple[ExtractionWork | LabellingWork, ExtractionWork | LabellingWork]:
    first = read_work(load_batch(first_batch), first_work)
    second = read_work(load_batch(second_batch), second_work)
    if first.phase is not second.phase:
        raise UtuxError(
            f"{first_work} is {first.phase.value} work and {second_work} is "
            f"{second.phase.value} work; a merge takes two works of one phase"
        )
    return first, second


BatchA = Annotated[Path, typer.Argument(help="The first annotator's batch.")]
WorkA = Annotated[Path, typer.Argument(help="The first annotator's work.")]
BatchB = Annotated[Path, typer.Argument(help="The second annotator's batch.")]
WorkB = Annotated[Path, typer.Argument(help="The second annotator's work.")]
ReferencesOption = Annotated[
    Path | None,
    typer.Option("--references", help="The reference claims; needed for the labelling phase."),
]


def _references(path: Path | None) -> ReferenceClaims:
    if path is None:
        raise UtuxError("the labelling phase needs --references, the merged claim lists")
    return ReferenceClaims.validate_document(
        json.loads(path.read_text(encoding="utf-8")), str(path)
    )


@gold_app.command("merge")
def merge(
    pool: Pool,
    batch_a: BatchA,
    work_a: WorkA,
    batch_b: BatchB,
    work_b: WorkB,
    out: Annotated[
        Path,
        typer.Option(
            "--out", help="Reference claims (claim extraction) or items, one per line (labelling)."
        ),
    ],
    disagreements: Annotated[
        Path, typer.Option("--disagreements", help="The list for the adjudicator.")
    ],
    references: ReferencesOption = None,
    adjudication: Annotated[
        Path | None, typer.Option("--adjudication", help="The adjudicator's decisions.")
    ] = None,
) -> None:
    """Merge two annotators' work: what is settled, and what is left to decide."""
    try:
        loaded = load_pool(pool)
        first, second = _two_works(batch_a, work_a, batch_b, work_b)
        decisions = None if adjudication is None else load_adjudication(adjudication)
        if isinstance(first, ExtractionWork) and isinstance(second, ExtractionWork):
            merged = merge_extraction(loaded, first, second, decisions)
            atomic_write_text(out, merged.references.to_json())
            settled, left = len(merged.references.items), merged.disagreements
        elif isinstance(first, LabellingWork) and isinstance(second, LabellingWork):
            labelled = merge_labelling(loaded, _references(references), first, second, decisions)
            atomic_write_text(out, release_text(labelled.items))
            settled, left = len(labelled.items), labelled.disagreements
        else:
            raise UtuxError("the two works are of different phases")
        atomic_write_text(disagreements, disagreements_json(left))
    except UtuxError as error:
        raise _fail(error) from error
    typer.echo(
        f"Settled {_count(settled, 'item')} into {out}; "
        f"{_count(len(left), 'disagreement')} for the adjudicator in {disagreements}."
    )


def _label_line(name: str, agreement: LabelAgreement) -> str:
    def measure(value: float | None) -> str:
        return "undefined" if value is None else f"{value:.3f}"

    return (
        f"{name}: {agreement.units} units, raw agreement {measure(agreement.raw_agreement)}, "
        f"Cohen's kappa {measure(agreement.cohens_kappa)}, Gwet's AC1 {measure(agreement.gwet_ac1)}"
    )


def _extraction_line(agreement: ExtractionAgreement) -> str:
    share = "undefined" if agreement.share is None else f"{agreement.share:.3f}"
    return (
        f"Claim extraction: {agreement.first} and {agreement.second} claims listed, "
        f"{agreement.matched} matched, share {share}"
    )


def _report_lines(report: AgreementReport) -> list[str]:
    lines = [
        _extraction_line(report.claim_extraction),
        _label_line("Status", report.status),
        _label_line("Expert would review", report.expert_would_review),
        _label_line("Agreement label", report.agreement_label),
    ]
    lines += [
        _label_line(f"Scope flag {flag}", value) for flag, value in report.scope_flags.items()
    ]
    spans = report.evidence_spans
    if spans is not None:
        f1 = "undefined" if spans.mean_f1 is None else f"{spans.mean_f1:.3f}"
        iou = "undefined" if spans.mean_iou is None else f"{spans.mean_iou:.3f}"
        lines.append(f"Evidence spans: {spans.pairs} pairs, mean F1 {f1}, mean IoU {iou}")
    return lines


@gold_app.command("agreement")
def agreement(
    pool: Pool,
    batch_a: BatchA,
    work_a: WorkA,
    batch_b: BatchB,
    work_b: WorkB,
    references: ReferencesOption = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Agreement between two annotators' work, before adjudication. Counts and measures only."""
    try:
        loaded = load_pool(pool)
        first, second = _two_works(batch_a, work_a, batch_b, work_b)
        if isinstance(first, ExtractionWork) and isinstance(second, ExtractionWork):
            extraction = extraction_agreement(first, second)
            document: object = {"claim_extraction": extraction.to_json()}
            lines = [_extraction_line(extraction)]
        elif isinstance(first, LabellingWork) and isinstance(second, LabellingWork):
            report = labelling_agreement(loaded, _references(references), first, second)
            document, lines = report.to_json(), _report_lines(report)
        else:
            raise UtuxError("the two works are of different phases")
    except UtuxError as error:
        raise _fail(error) from error
    if as_json:
        typer.echo(json.dumps(document, indent=2))
        return
    for line in lines:
        typer.echo(line)


Items = Annotated[Path, typer.Argument(help="The merged items, one gold item per line.")]


@gold_app.command("split-report")
def report(
    items: Items,
    seed: SeedOption,
    dev_share: DevShare = DEV_SHARE,
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Compare the strata of dev and test under a seed, to choose one before the freeze."""
    try:
        loaded = read_items(items)
        split = split_report(
            with_splits(loaded, assign_splits(loaded, dev_share=dev_share, seed=seed))
        )
    except UtuxError as error:
        raise _fail(error) from error
    if as_json:
        typer.echo(json.dumps(split.to_json(), indent=2))
        return
    for line in split.lines():
        typer.echo(line)


@gold_app.command("freeze")
def freeze(
    items: Items,
    seed: SeedOption,
    out: Annotated[Path, typer.Option("--out", help="The release file to write.")],
    dev_share: DevShare = DEV_SHARE,
) -> None:
    """Set every item's split from the seed, check the release, and write it once."""
    try:
        if out.exists():
            raise UtuxError(f"{out} exists; a frozen release is never written over")
        loaded = read_items(items)
        # The release rules first, on the items as they are; the split comes next.
        before = [p for p in check_release(loaded).problems if p.code != "split_not_set"]
        if before:
            raise ContractValidationError(str(items), tuple(before))
        frozen = with_splits(loaded, assign_splits(loaded, dev_share=dev_share, seed=seed))
        checked = check_release(frozen)
        if checked.problems:
            raise ContractValidationError(str(items), checked.problems)
        atomic_write_text(out, release_text(frozen))
    except UtuxError as error:
        raise _fail(error) from error
    for departure in checked.departures:
        typer.echo(f"departure: {departure.field}: {departure.reason} ({departure.code})")
    dev = sum(1 for item in frozen if item.split is not None and item.split.value == "dev")
    typer.echo(
        f"Froze {_count(len(frozen), 'item')} into {out}: dev {dev}, test {len(frozen) - dev}."
    )
    typer.echo(
        f"Release {frozen[0].gold_version if frozen else ''}, content hash {hash_file(out)}. "
        "Record the version, this hash and a changelog with the release."
    )


@gold_app.command("import-public")
def import_public_dataset(
    dataset: Annotated[PublicDataset, typer.Argument(help="scifact or sciclaimeval.")],
    directory: Annotated[
        Path, typer.Argument(help="The downloaded release, outside the repository.")
    ],
    out: Annotated[
        Path,
        typer.Option("--out", help="The directory to write into, outside any git work tree."),
    ],
) -> None:
    """Map a public dataset into gold items and print the counts, never an item.

    Writes `items.jsonl` (gold items of origin `public`) and `sources/`, the
    source texts by hash.
    """
    try:
        result = import_public(dataset, directory)
        write_public_import(out, result)
    except UtuxError as error:
        raise _fail(error) from error
    typer.echo(f"Wrote {_count(len(result.items), 'item')} to {out}")
    typer.echo(json.dumps(summarize(result), indent=2, sort_keys=True))


# M0-15c: perturbations, the v0 sample and the audit. Every command prints
# counts only, never an item, a text or a label.

Imported = Annotated[
    list[Path],
    typer.Option("--imported", help="A directory written by import-public; give each one."),
]


def _write_items(path: Path, items: Sequence[GoldItem]) -> None:
    ensure_outside_git(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, release_text(items))


def _parent_ids(parents: Path | None) -> list[str] | None:
    return None if parents is None else [item.item_id for item in read_gold_release(parents)]


@gold_app.command("perturb")
def perturb(
    imported: Imported,
    method: Annotated[str, typer.Option("--method", help="rules, or gemini (ADR-0019).")],
    out: Annotated[Path, typer.Option("--out", help="The directory to write into.")],
    parents: Annotated[
        Path | None, typer.Option("--parents", help="Only these parents: parents.jsonl of sample.")
    ] = None,
    seed: Annotated[int, typer.Option("--seed", help="The seed of the parent order.")] = 7,
    max_uncited: Annotated[
        int, typer.Option("--max-uncited", help="The cap on uncited abstracts.")
    ] = MAX_UNCITED,
    max_cost_usd: Annotated[
        float | None,
        typer.Option("--max-cost-usd", help="gemini: the cap, at the higher price (ADR-0019)."),
    ] = None,
    per_type: Annotated[
        int, typer.Option("--per-type", help="gemini: checked items wanted per type.")
    ] = 15,
) -> None:
    """Build perturbations whose labels follow from their construction."""
    if method not in ("rules", "gemini"):
        raise typer.BadParameter("must be rules or gemini", param_hint="--method")
    if method == "gemini" and max_cost_usd is None:
        raise typer.BadParameter("gemini needs a cost cap", param_hint="--max-cost-usd")
    try:
        ensure_outside_git(out)
        items, texts = load_imported(imported)
        allowed = _parent_ids(parents)
        if method == "rules":
            run = build_rule_perturbations(
                items, texts, seed=seed, parents=allowed, max_uncited=max_uncited
            )
            extra: dict[str, object] = {}
        else:
            if not os.environ.get(GEMINI_KEY_VARIABLE, "").strip():
                raise ModelAuthenticationError(
                    f"{GEMINI_KEY_VARIABLE} is not set; the key is read only from it, and "
                    "nothing was sent"
                )
            out.mkdir(parents=True, exist_ok=True)
            caller = CappedCaller(
                EventLog(out / "events.jsonl"), gemini_provider(), max_cost_usd=max_cost_usd or 0.0
            )
            run = build_model_perturbations(
                items, texts, caller, seed=seed, per_type=per_type, parents=allowed
            )
            extra = {
                "estimated_cost_usd (an estimate, ADR-0019)": round(caller.estimated_usd, 4),
                "counted_against_cap_usd": round(caller.spent_cap_usd, 4),
            }
        path = out / f"perturbed-{method}.jsonl"
        _write_items(path, run.items)
    except UtuxError as error:
        raise _fail(error) from error
    typer.echo(f"Wrote {_count(len(run.items), 'item')} to {path}")
    typer.echo(json.dumps({**run.summary(), **extra}, indent=2, sort_keys=True))


@gold_app.command("sample")
def sample(
    imported: Imported,
    seed: Annotated[int, typer.Option("--seed", help="The seed of the sample; record it.")],
    out: Annotated[Path, typer.Option("--out", help="The directory to write into.")],
    perturbed: Annotated[
        list[Path] | None,
        typer.Option("--perturbed", help="Files written by perturb; without them, parents only."),
    ] = None,
    scifact_per_status: Annotated[int, typer.Option("--scifact-per-status")] = 50,
    sciclaimeval_per_status: Annotated[int, typer.Option("--sciclaimeval-per-status")] = 50,
    perturbations: Annotated[int, typer.Option("--perturbations")] = 50,
    max_uncited: Annotated[int, typer.Option("--max-uncited")] = MAX_UNCITED,
    dev_share: Annotated[float, typer.Option("--dev-share")] = SAMPLE_DEV_SHARE,
) -> None:
    """Draw the v0 sample by a fixed seed; with --perturbed, add them and split by group."""
    sizes = SampleSizes(scifact_per_status, sciclaimeval_per_status, perturbations, max_uncited)
    try:
        ensure_outside_git(out)
        items, texts = load_imported(imported)
        if not perturbed:
            parents = select_imported(items, sizes, seed=seed)
            _write_items(out / "parents.jsonl", parents)
            typer.echo(f"Wrote {_count(len(parents), 'parent')} to {out / 'parents.jsonl'}")
            counts = Counter(
                f"{i.provenance.dataset.value if i.provenance else '?'} "
                f"{i.domain.value} {i.claims[0].status.value}"
                for i in parents
            )
            typer.echo(
                json.dumps({"seed": seed, "parents": dict(sorted(counts.items()))}, indent=2)
            )
            return
        children = [child for path in perturbed for child in read_gold_release(path)]
        drawn = sample_v0(items, children, sizes, seed=seed, dev_share=dev_share)
        _write_items(out / "v0.jsonl", drawn.items)
        used = {p.text_hash for item in drawn.items for c in item.claims for p in c.pairs}
        (out / "sources").mkdir(parents=True, exist_ok=True)
        for text_hash in sorted(used):
            atomic_write_text(
                out / "sources" / f"{text_hash.removeprefix('sha256:')}.txt", texts[text_hash]
            )
        record = {
            **drawn.report(),
            "inputs": {
                str(p): hash_file(p) for p in [*(d / "items.jsonl" for d in imported), *perturbed]
            },
            "release_hash": hash_file(out / "v0.jsonl"),
        }
        atomic_write_text(out / "sample-record.json", json.dumps(record, indent=2) + "\n")
    except UtuxError as error:
        raise _fail(error) from error
    typer.echo(f"Wrote {_count(len(drawn.items), 'item')} to {out / 'v0.jsonl'}")
    typer.echo(json.dumps(drawn.report(), indent=2, sort_keys=True))


audit_app = typer.Typer(help="The maintainer's blind audit of gold v0.")
gold_app.add_typer(audit_app, name="audit")


def _release_texts(release: Path) -> dict[str, str]:
    return {
        f"sha256:{path.stem}": path.read_text(encoding="utf-8")
        for path in sorted((release.parent / "sources").glob("*.txt"))
    }


@audit_app.command("export")
def audit_export(
    release: Annotated[Path, typer.Option("--release", help="v0.jsonl written by sample.")],
    seed: Annotated[int, typer.Option("--seed", help="The seed of the audit; record it.")],
    out: Annotated[Path, typer.Option("--out", help="The directory to write into.")],
) -> None:
    """Write the blind sheet of 30 items, and its key."""
    try:
        ensure_outside_git(out)
        sheet, key = export_audit(read_gold_release(release), _release_texts(release), seed=seed)
        out.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out / "audit-sheet.csv", sheet)
        atomic_write_text(out / "audit-key.json", json.dumps(key, indent=2) + "\n")
    except UtuxError as error:
        raise _fail(error) from error
    typer.echo(f"Wrote {_count(len(key), 'row')} to {out / 'audit-sheet.csv'}")
    typer.echo(f"Wrote the key to {out / 'audit-key.json'}; do not open it before scoring.")


@audit_app.command("score")
def audit_score(
    release: Annotated[Path, typer.Option("--release", help="v0.jsonl written by sample.")],
    key: Annotated[Path, typer.Option("--key", help="audit-key.json.")],
    sheet: Annotated[Path, typer.Option("--sheet", help="The filled audit-sheet.csv.")],
    annotator: Annotated[str, typer.Option("--annotator", help="Your pseudonymous id, a01.")],
    out: Annotated[Path, typer.Option("--out", help="The release to write, with upgrades.")],
) -> None:
    """Score the filled sheet: Cohen's kappa, and confirmed items upgraded to audit."""
    try:
        keys = json.loads(key.read_text(encoding="utf-8"))
        result = score_audit(
            read_gold_release(release), keys, sheet.read_text(encoding="utf-8"), annotator=annotator
        )
        _write_items(out, result.items)
    except UtuxError as error:
        raise _fail(error) from error
    typer.echo(json.dumps(result.report(), indent=2, sort_keys=True))
    if result.below_floor:
        typer.echo("Kappa is below 0.6, or cannot be computed: review the label mapping.")


def _openalex_search(log: EventLog) -> LoggedLiteratureSource:
    """OpenAlex, logged to `log`; replaced by a synthetic search in tests."""
    return LoggedLiteratureSource(log, OpenAlexSource(), policy=DataPolicy.EXTERNAL_ALLOWED)


@gold_app.command("existence-items")
def existence_items(
    scifact: Annotated[Path, typer.Option("--scifact", help="The downloaded SciFact release.")],
    release: Annotated[
        Path, typer.Option("--release", help="parents.jsonl or v0.jsonl: its SciFact abstracts.")
    ],
    seed: Annotated[int, typer.Option("--seed", help="The seed of the split; record it.")],
    out: Annotated[Path, typer.Option("--out", help="The directory to write into.")],
    max_documents: Annotated[
        int, typer.Option("--max-documents", help="At most this many titles are searched.")
    ] = 60,
) -> None:
    """Build citation existence items from SciFact titles found by OpenAlex. Network calls."""
    try:
        ensure_outside_git(out)
        doc_ids = sorted(
            {
                pair.source_id.removeprefix("scifact-doc-")
                for item in read_gold_release(release)
                for claim in item.claims
                for pair in claim.pairs
                if pair.source_id.startswith("scifact-doc-")
            }
        )
        chosen = sorted(random.Random(seed).sample(doc_ids, min(max_documents, len(doc_ids))))
        titles = scifact_titles(scifact, chosen)
        out.mkdir(parents=True, exist_ok=True)
        records, dropped = find_real_references(
            titles, _openalex_search(EventLog(out / "events.jsonl"))
        )
        items = build_existence_items(records, seed=seed)
        atomic_write_text(
            out / "existence-items.jsonl", "".join(item.to_json_line() for item in items)
        )
    except UtuxError as error:
        raise _fail(error) from error
    summary = {
        "titles_searched": len(titles),
        "real_references": len(records),
        "dropped": dict(sorted(dropped.items())),
        "items": len(items),
        "by_construction": dict(sorted(Counter(i.construction.value for i in items).items())),
        "by_split": dict(sorted(Counter(str(i.split) for i in items).items())),
    }
    typer.echo(f"Wrote {_count(len(items), 'item')} to {out / 'existence-items.jsonl'}")
    typer.echo(json.dumps(summary, indent=2, sort_keys=True))
