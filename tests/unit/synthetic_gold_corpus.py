"""A small synthetic imported corpus for the gold v0 tooling tests (M0-15c).

Every claim, abstract and table here is synthetic, written in the shape of
SciFact and SciClaimEval and imported with `utux gold import-public`'s own
code, so the items are real `public` gold items with their source texts.
"""

import json
from pathlib import Path

from utux.evalkit.gold import GoldItem, PublicDataset
from utux.evalkit.public import import_public

ABSTRACTS = {
    101: [
        "Synthetic drug A was given to 40 mice.",
        "Drug A lowered blood pressure by 12 percent in the mice.",
        "No side effects were seen.",
    ],
    102: ["Synthetic drug B was tested in 30 rats.", "Drug B raised heart rate in the rats."],
    103: ["A synthetic survey of 9 clinics.", "It reports staffing only."],
    # Shares words with claim 1 but is not cited by it: the uncited abstract.
    104: ["Drug A and blood pressure in synthetic rabbits.", "Results are pending."],
    105: ["Synthetic drug C was given to 50 dogs.", "Drug C did not change mortality."],
}

CLAIMS = [
    # verified, with a number that is in its evidence
    (1, "Drug A potentially lowered blood pressure by 12 percent in mice.", {"101": [1]}, [101]),
    # verified, no number, no hedge
    (2, "Drug B raised heart rate in rats.", {"102": [1]}, [102]),
    # contradicted
    (3, "Drug C lowered mortality in dogs.", {"105": [1]}, [105], "CONTRADICT"),
    # insufficient evidence
    (4, "Clinics are understaffed.", {}, [103, 104]),
]

TABLE = {
    "table_caption": "Table 1: Synthetic accuracy of two models.",
    "table_column_names": ["Model", "Accuracy"],
    "table_content_values": [["Alpha", "81.0"], ["Beta", "77.5"]],
}


def _scifact(root: Path) -> Path:
    data = root / "scifact" / "data"
    data.mkdir(parents=True)
    corpus = [
        {"doc_id": doc, "title": f"Synthetic {doc}", "abstract": text, "structured": False}
        for doc, text in ABSTRACTS.items()
    ]
    (data / "corpus.jsonl").write_text("".join(json.dumps(r) + "\n" for r in corpus), "utf-8")
    claims = []
    for row in CLAIMS:
        claim_id, text, evidence, cited = row[:4]
        label = row[4] if len(row) > 4 else "SUPPORT"
        claims.append(
            {
                "id": claim_id,
                "claim": text,
                "evidence": {
                    doc: [{"sentences": sentences, "label": label}]
                    for doc, sentences in evidence.items()
                },
                "cited_doc_ids": cited,
            }
        )
    (data / "claims_train.jsonl").write_text("".join(json.dumps(c) + "\n" for c in claims), "utf-8")
    (data / "claims_dev.jsonl").write_text("", "utf-8")
    return root / "scifact"


def _sample(number: int, claim: str, label: str, domain: str = "ml") -> dict[str, object]:
    return {
        "claim_id": f"val_tab_{number:04d}",
        "claim": claim,
        "label": label,
        "evi_type": "table",
        "use_context": "no",
        "context": "",
        "domain": domain,
        "paper_id": f"synthetic-paper-{number}",
        "license_name": "CC BY 4.0",
    }


def _sciclaimeval(root: Path) -> Path:
    data = root / "sciclaimeval" / "data"
    (data / "tables_json" / "dev").mkdir(parents=True)
    samples = [
        _sample(1, "Alpha reaches an accuracy of 81.0.", "Supported"),
        _sample(2, "Beta beats Alpha in accuracy.", "Refuted"),
        _sample(3, "Alpha is the best synthetic model.", "Supported", domain="peerj"),
    ]
    (data / "dev_task1_release.json").write_text(json.dumps(samples), "utf-8")
    for sample in samples:
        path = data / "tables_json" / "dev" / f"{sample['claim_id']}.json"
        path.write_text(json.dumps(TABLE), "utf-8")
    return root / "sciclaimeval"


def synthetic_corpus(root: Path) -> tuple[tuple[GoldItem, ...], dict[str, str]]:
    """Import the synthetic datasets: the items of both, and their texts by hash."""
    scifact = import_public(PublicDataset.SCIFACT, _scifact(root))
    sciclaimeval = import_public(PublicDataset.SCICLAIMEVAL, _sciclaimeval(root))
    return (scifact.items + sciclaimeval.items, {**scifact.texts, **sciclaimeval.texts})


def item(items: tuple[GoldItem, ...], item_id: str) -> GoldItem:
    """The item with this id."""
    return next(i for i in items if i.item_id == item_id)
