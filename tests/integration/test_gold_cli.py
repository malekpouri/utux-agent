"""PR #48 review: the `utux gold` commands, thin over `utux.evalkit.annotation`.

The pool is the synthetic fixture of `tests/fixtures/annotation_pool`; the
claims and labels below stand in for the annotators and are synthetic.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from utux.cli import app
from utux.evalkit.gold import read_gold_release
from utux.schemas.claim_ledger import CheckedText
from utux.sources.passages import split_passages
from utux.workspace.hashing import hash_file

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
POOL = FIXTURES / "annotation_pool" / "valid" / "synthetic_natural.json"
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})

CLAIMS = [
    {
        "span": [0, 47],
        "text": "Method A outperforms method B on dataset X.",
        "kind": "finding",
        "citations": ["doi:10.0000/synthetic"],
    },
    {"span": [48, 65], "text": "Method A is fast.", "kind": "method", "citations": []},
]


def _gold(*arguments: str) -> tuple[int, str]:
    result = runner.invoke(app, ["gold", *arguments])
    return result.exit_code, result.output


def _write(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path


def _batch(directory: Path, phase: str, annotator: str, *extra: str) -> dict[str, Any]:
    code, output = _gold(
        "batch",
        str(POOL),
        "--phase",
        phase,
        "--annotator",
        annotator,
        "--batch-id",
        "b01",
        "--out",
        str(directory),
        *extra,
    )
    assert code == 0, output
    path = directory / f"batch-b01-{annotator}-{phase}.json"
    assert str(path) in output
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _work(batch: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "phase": batch["phase"],
        "batch_id": batch["batch_id"],
        "batch_hash": batch["batch_hash"],
        "annotator": batch["annotator"],
        "items": items,
    }


def _passage_id(index: int) -> str:
    """A passage id of the pool's source, from the shared splitter (M2-02)."""
    source = json.loads(POOL.read_text(encoding="utf-8"))["items"][0]["sources"][0]
    passages = split_passages(source["text"], CheckedText(source["checked_text"]))
    return passages[index].passage_id


def _labels(status: str) -> list[dict[str, Any]]:
    pair = {
        "source_id": "doi:10.0000/synthetic",
        "evidence_spans": [{"passage_id": _passage_id(1), "offsets": [20, 43]}],
        "agreement_label": "entails",
        "scope_flags": [],
        "note": None,
    }
    claims = [
        {
            "claim_id": "G0001-c1",
            "status": status,
            "expert_would_review": False,
            "note": None,
            "pairs": [pair],
        },
        {
            "claim_id": "G0001-c2",
            "status": "insufficient_evidence",
            "expert_would_review": False,
            "note": None,
            "pairs": [],
        },
    ]
    return [{"item_id": "G0001", "claims": claims, "flag": None, "minutes": None}]


@pytest.mark.parametrize(
    "command",
    ["pool-check", "batch", "import", "merge", "agreement", "split-report", "freeze"],
)
def test_every_gold_command_has_help(command: str) -> None:
    code, output = _gold(command, "--help")
    assert code == 0, output
    assert "Usage" in output


def test_pool_check_reports_a_valid_pool_and_refuses_an_invalid_one(tmp_path: Path) -> None:
    code, output = _gold("pool-check", str(POOL))
    assert code == 0, output
    assert "1 item" in output
    broken = json.loads(POOL.read_text(encoding="utf-8"))
    broken["items"].append(broken["items"][0])
    code, output = _gold("pool-check", str(_write(tmp_path / "pool.json", broken)))
    assert code == 1
    assert "duplicate_item_id" in output


def test_from_pool_to_frozen_release(tmp_path: Path) -> None:
    # Phase 1: two batches, the page beside them, two claim lists.
    first = _batch(tmp_path, "claim_extraction", "a03")
    second = _batch(tmp_path, "claim_extraction", "a07")
    assert (tmp_path / "annotation_page.html").is_file()
    item = {"item_id": "G0001", "claims": CLAIMS, "flag": None, "minutes": 5}
    work_a = _write(tmp_path / "work-a03-1.json", _work(first, [item]))
    work_b = _write(tmp_path / "work-a07-1.json", _work(second, [item]))
    batch_a = tmp_path / "batch-b01-a03-claim_extraction.json"
    batch_b = tmp_path / "batch-b01-a07-claim_extraction.json"
    code, output = _gold("import", str(batch_a), str(work_a))
    assert code == 0, output
    assert "1 item" in output
    code, output = _gold(
        "agreement", str(POOL), str(batch_a), str(work_a), str(batch_b), str(work_b)
    )
    assert code == 0, output
    assert "Claim extraction" in output
    references = tmp_path / "references.json"
    disagreements = tmp_path / "disagreements-1.json"
    code, output = _gold(
        "merge",
        str(POOL),
        str(batch_a),
        str(work_a),
        str(batch_b),
        str(work_b),
        "--out",
        str(references),
        "--disagreements",
        str(disagreements),
    )
    assert code == 0, output
    assert json.loads(disagreements.read_text(encoding="utf-8")) == []

    # Phase 2: batches with the reference claims, two label sets that differ once.
    third = _batch(tmp_path, "labelling", "a03", "--references", str(references))
    fourth = _batch(tmp_path, "labelling", "a07", "--references", str(references))
    labels_a = _write(tmp_path / "work-a03-2.json", _work(third, _labels("verified")))
    labels_b = _write(tmp_path / "work-a07-2.json", _work(fourth, _labels("partially_supported")))
    batch_c = tmp_path / "batch-b01-a03-labelling.json"
    batch_d = tmp_path / "batch-b01-a07-labelling.json"
    code, output = _gold(
        "agreement",
        str(POOL),
        str(batch_c),
        str(labels_a),
        str(batch_d),
        str(labels_b),
        "--references",
        str(references),
        "--json",
    )
    assert code == 0, output
    assert json.loads(output)["status"]["raw_agreement"] == 0.5
    items = tmp_path / "items.jsonl"
    disagreements = tmp_path / "disagreements-2.json"
    merge = [
        "merge",
        str(POOL),
        str(batch_c),
        str(labels_a),
        str(batch_d),
        str(labels_b),
        "--references",
        str(references),
        "--out",
        str(items),
        "--disagreements",
        str(disagreements),
    ]
    code, output = _gold(*merge)
    assert code == 0, output
    (left,) = json.loads(disagreements.read_text(encoding="utf-8"))
    assert (left["level"], left["target"]) == ("claim", "G0001-c1")
    assert items.read_text(encoding="utf-8") == ""

    # The adjudicator decides, and the merge makes the item, without a split.
    adjudication = _write(
        tmp_path / "adjudication.json",
        {
            "schema_version": 1,
            "phase": "labelling",
            "adjudicator": "a01",
            "claims": [
                {
                    "claim_id": "G0001-c1",
                    "status": "partially_supported",
                    "expert_would_review": True,
                    "reason": "Synthetic reason.",
                }
            ],
        },
    )
    code, output = _gold(*merge, "--adjudication", str(adjudication))
    assert code == 0, output
    (made,) = read_gold_release(items)
    assert made.split is None

    # The split report and the freeze set the split from the seed.
    code, output = _gold("split-report", str(items), "--seed", "7")
    assert code == 0, output
    assert "Items:" in output
    release = tmp_path / "release.jsonl"
    code, output = _gold("freeze", str(items), "--seed", "7", "--out", str(release))
    assert code == 0, output
    (frozen,) = read_gold_release(release)
    assert frozen.split is not None
    assert hash_file(release) in output


def test_freeze_refuses_a_release_with_problems_and_an_existing_file(tmp_path: Path) -> None:
    source = FIXTURES / "gold_release" / "synthetic_release.jsonl"
    lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
    broken = tmp_path / "items.jsonl"
    broken.write_text(lines[0] + lines[0], encoding="utf-8")
    code, output = _gold("freeze", str(broken), "--seed", "1", "--out", str(tmp_path / "r.jsonl"))
    assert code == 1
    assert "duplicate_item_id" in output
    assert not (tmp_path / "r.jsonl").exists()
    good = tmp_path / "good.jsonl"
    shutil.copy(source, good)
    (tmp_path / "taken.jsonl").write_text("", encoding="utf-8")
    code, output = _gold("freeze", str(good), "--seed", "1", "--out", str(tmp_path / "taken.jsonl"))
    assert code == 1
    assert "exists" in output


def test_import_reports_every_problem_of_a_work_file(tmp_path: Path) -> None:
    batch = _batch(tmp_path, "claim_extraction", "a03")
    wrong = dict(CLAIMS[0], citations=["doi:10.0000/other"])
    work = _write(
        tmp_path / "work.json",
        _work(batch, [{"item_id": "G0001", "claims": [wrong], "flag": None, "minutes": None}]),
    )
    code, output = _gold("import", str(tmp_path / "batch-b01-a03-claim_extraction.json"), str(work))
    assert code == 1
    assert re.search(r"unknown_source", output)


# M0-15b: utux gold import-public, on a synthetic SciClaimEval release.


def test_import_public_writes_items_and_prints_counts_only(tmp_path: Path) -> None:
    from utux.evalkit.public import read_public_items

    data = tmp_path / "sciclaimeval" / "data"
    (data / "tables_json" / "dev").mkdir(parents=True)
    sample = {
        "claim_id": "val_tab_0001",
        "claim": "Synthetic model Alpha beats Beta.",
        "label": "Supported",
        "evi_type": "table",
        "use_context": "no",
        "context": "",
        "domain": "ml",
        "license_name": "CC BY 4.0",
    }
    figure = dict(sample, claim_id="val_fig_0002", evi_type="figure")
    _write(data / "dev_task1_release.json", [sample, figure])
    _write(
        data / "tables_json" / "dev" / "val_tab_0001.json",
        {
            "table_caption": "Synthetic table.",
            "table_column_names": ["Model", "Score"],
            "table_content_values": [["Alpha", "2"], ["Beta", "1"]],
        },
    )
    out = tmp_path / "items" / "sciclaimeval.jsonl"
    code, output = _gold(
        "import-public", "sciclaimeval", str(tmp_path / "sciclaimeval"), "--out", str(out)
    )
    assert code == 0, output
    assert len(read_public_items(out)) == 1
    counts = json.loads(output[output.index("{") :])
    assert counts["items"] == 1
    assert counts["dropped"] == {"dev": {"evidence_figure": 1}}
    assert "Alpha" not in output


def test_import_public_refuses_an_output_inside_a_git_work_tree(tmp_path: Path) -> None:
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    data = tmp_path / "sciclaimeval" / "data"
    data.mkdir(parents=True)
    _write(data / "dev_task1_release.json", [])
    code, output = _gold(
        "import-public",
        "sciclaimeval",
        str(tmp_path / "sciclaimeval"),
        "--out",
        str(tmp_path / "repo" / "items.jsonl"),
    )
    assert code == 1
    assert "git work tree" in output
