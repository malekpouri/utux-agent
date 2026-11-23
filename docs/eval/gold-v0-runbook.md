# Gold v0 runbook

The maintainer's steps to build gold set v0, by the
[gold v0 strategy](gold-v0-strategy.md) (ADR-0018) and task M0-15c. Every
output stays in `~/utux-data/gold`, outside the repository; the commands
refuse to write inside any git work tree. Every command prints counts only.

The seeds below are the ones recorded for v0. Keep them, or record new ones
before you run.

## 0. Before you start

The imports of `utux gold import-public` are in `~/utux-data/gold/items/scifact`
and `~/utux-data/gold/items/sciclaimeval` ([datasets.md](datasets.md)).

## 1. Draw the parents

The 250 imported items of v0, by seed:
- SciFact: 50 `verified`, 50 `contradicted` and 50 `insufficient_evidence`;
- SciClaimEval ML: 50 `verified` and 50 `contradicted`.

```bash
uv run utux gold sample \
  --imported ~/utux-data/gold/items/scifact --imported ~/utux-data/gold/items/sciclaimeval \
  --seed 20261123 --out ~/utux-data/gold/v0-parents
```

## 2. Rule-made perturbations, no model

Built from the `verified` parents. Each child records
`confirmation: deterministic`.

```bash
uv run utux gold perturb \
  --imported ~/utux-data/gold/items/scifact --imported ~/utux-data/gold/items/sciclaimeval \
  --parents ~/utux-data/gold/v0-parents/parents.jsonl \
  --method rules --seed 7 --out ~/utux-data/gold/v0-perturbed
```

| Type | Label by construction | Deterministic check |
| --- | --- | --- |
| Uncited abstract (SciFact only, at most 10) | pair `neutral`, `insufficient_evidence` | the abstract is the most similar one the claim does not cite |
| Number change | pair `contradicts`, flag `magnitude_mismatch`, `contradicted` | the changed number is in the evidence; the new one is nowhere in the source texts; years are left alone |
| Hedge removal | flag `certainty_escalation`, status by the guideline | the removed hedge word was in the claim |
| Metric swap | flag `metric_mismatch`, status by the guideline | the metric is in the evidence; the new one is nowhere in the source texts |

**The fixed lists** are in `utux.evalkit.perturb`:
- **Hedges** (adverbs only, so that removing one leaves a sentence):
  possibly, probably, potentially, perhaps, presumably, apparently,
  seemingly, conceivably, plausibly, arguably.
- **ML metrics:** accuracy, precision, recall, F1, BLEU, ROUGE, perplexity,
  AUC.
- **Biomedical metrics:** mortality, incidence, prevalence, sensitivity,
  specificity, survival.

**Labels.** The parent's pair labels are kept, except where the type names
one. The flag is added to the supporting pairs, and the status is
`guideline_status`. So:
- a minor flag (`certainty_escalation`, `missing_comparator`) leaves an
  entailed claim `verified`;
- a major or critical flag without a contradiction gives
  `partially_supported`.

## 3. Model-written perturbations, with Gemini

Direction, causal, overgeneralisation and missing comparator. Gemini writes
each item and checks it in a separate call that only flags disagreement.
Flagged items are dropped and counted. The others record
`confirmation: model_check`. ML parents are tried first.

1. **Check the price table.** Compare the table in
   `utux.evalkit.model_perturb` (`PRICES`, read on 2026-11-23) with the
   [pricing page](https://aistudio.google.com/docs/pricing). The cap uses the
   higher price whatever the table says (ADR-0019).
2. **Use a paid-tier key.** The key must belong to a project with billing
   enabled (Paid Services), and is read only from the environment:

   ```bash
   export GEMINI_API_KEY=...        # never in utux.yaml or a file in the repository
   uv run utux gold perturb \
     --imported ~/utux-data/gold/items/scifact --imported ~/utux-data/gold/items/sciclaimeval \
     --parents ~/utux-data/gold/v0-parents/parents.jsonl \
     --method gemini --max-cost-usd 5 --per-type 15 --seed 7 \
     --out ~/utux-data/gold/v0-perturbed
   ```

3. **Read the run.** Every call is a `model_call` event in
   `~/utux-data/gold/v0-perturbed/events.jsonl`, with `estimated_cost_usd`, an
   estimate from the table; `cost_usd` stays null, as Gemini reports none.
   The command prints the estimate and the amount counted against the cap.
   A call that could pass the cap is refused (`budget_exhausted`) and the
   run stops.

## 4. Draw v0

The 250 parents, about 50 perturbations of those parents (types in turn, ML
first, at most 10 uncited abstracts), and the split by source group (30%
`dev`).

```bash
uv run utux gold sample \
  --imported ~/utux-data/gold/items/scifact --imported ~/utux-data/gold/items/sciclaimeval \
  --perturbed ~/utux-data/gold/v0-perturbed/perturbed-rules.jsonl \
  --perturbed ~/utux-data/gold/v0-perturbed/perturbed-gemini.jsonl \
  --seed 20261123 --out ~/utux-data/gold/v0
```

It writes:
- `v0.jsonl`;
- `sources/`, the texts it needs;
- `sample-record.json`: the seed, the counts per split, origin, status,
  domain and confirmation, the ML share, and the hashes of its inputs and
  of `v0.jsonl`.

## 5. The audit

```bash
uv run utux gold audit export \
  --release ~/utux-data/gold/v0/v0.jsonl --seed 20261123 --out ~/utux-data/gold/v0/audit
```

1. **The sheet.** Open `audit-sheet.csv`: 30 rows (20 model-written items
   and 10 imported ones) with the claim and the evidence. Fill the `status`
   column with `verified`, `partially_supported`, `contradicted` or
   `insufficient_evidence`, from the claim and the evidence only.
2. **The key.** Do not open `audit-key.json` before scoring.
3. **Score it:**

   ```bash
   uv run utux gold audit score \
     --release ~/utux-data/gold/v0/v0.jsonl \
     --key ~/utux-data/gold/v0/audit/audit-key.json \
     --sheet ~/utux-data/gold/v0/audit/audit-sheet.csv \
     --annotator a01 --out ~/utux-data/gold/v0/v0-audited.jsonl
   ```

   It prints Cohen's kappa against the constructed labels.
   - **Below 0.6, or not computable:** the label mapping is reviewed.
   - **Model-written items you agreed with** become `confirmation: audit`
     with your id.
   - **Labels never change.**

## 6. Then

`utux gold split-report` and `utux gold freeze` on `v0-audited.jsonl`
([Annotation tooling](../annotation-tooling.md)).
