"""`utux gold`: the commands of the gold-set tooling, thin over `utux.evalkit`.

They read and write the files of `docs/annotation-tooling.md`. They hold no
logic of their own and never write, suggest or change a label.
"""

import json
from pathlib import Path
from typing import Annotated

import typer

from utux.errors import ContractValidationError, UtuxError
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
from utux.evalkit.gold import check_release
from utux.evalkit.public import PublicDataset, import_public, summarize, write_public_items
from utux.evalkit.splits import assign_splits, split_report
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
        Path, typer.Option("--out", help="The items file to write, outside any git work tree.")
    ],
) -> None:
    """Map a public dataset into gold v0 items and print the counts, never an item."""
    try:
        result = import_public(dataset, directory)
        write_public_items(out, result.items)
    except UtuxError as error:
        raise _fail(error) from error
    typer.echo(f"Wrote {_count(len(result.items), 'item')} to {out}")
    typer.echo(json.dumps(summarize(result), indent=2, sort_keys=True))
