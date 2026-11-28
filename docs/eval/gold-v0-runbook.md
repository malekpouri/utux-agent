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
| Metric swap | flag `metric_mismatch`, status by the guideline | the metric is in the evidence; the new one is nowhere in the source texts |

**The fixed lists** are in `utux.evalkit.perturb`:
- **Hedges**, for the hedge-removal check of step 3: the adverbs possibly,
  probably, potentially, perhaps, presumably, apparently, seemingly,
  conceivably, plausibly, arguably; the modal verbs may, might, could; and the
  hedging verbs suggests, suggest, suggested, appears to, appear to, appeared
  to, seems to, seem to, seemed to.
- **ML metrics:** accuracy, precision, recall, F1, BLEU, ROUGE, perplexity,
  AUC.
- **Biomedical metrics:** mortality, incidence, prevalence, sensitivity,
  specificity, survival.

**Labels.** The parent's pair labels are kept, except where the type names
one. The flag is added to the supporting pairs, and the status follows
RFC-001's severity table (strategy, third review):
- a minor flag (`certainty_escalation`, `missing_comparator`) leaves an
  entailed claim `verified`;
- a major flag (`metric_mismatch`, `overgeneralisation`) gives
  `partially_supported`.

Causal overreach, a critical flag, is on hold until its status is decided.

## 3. Model-written perturbations, with Gemini

Hedge removal, direction, overgeneralisation and missing comparator; causal
overreach is on hold. Gemini writes each item and checks it in a separate
call that only flags disagreement.
- **Dropped and counted:** flagged items, and hedge removals that leave every
  hedge of the parent in place (`hedge_not_removed`).
- **Kept:** the others record `confirmation: model_check`.
- **Parents:** ML parents are tried first. A parent without a hedge is
  skipped for hedge removal before any call.
- **Every request** sets `thinking_level` `low` and `max_tokens` 2048. Before
  each call, its worst case at the cap price (the input by its bytes, and
  2048 output tokens, thinking included) is reserved against
  `--max-cost-usd`; a call whose reservation would pass the cap is refused
  and the run stops (ADR-0019).

1. **Check the price table.** Compare the table in
   `utux.evalkit.model_perturb` (`PRICES`, read on 2026-11-23) with the
   [pricing page](https://aistudio.google.com/docs/pricing). The cap uses the
   higher price whatever the table says (ADR-0019).
2. **Use a paid-tier key.** The key must belong to a project with billing
   enabled (Paid Services), and is read only from the environment:

   ```bash
   export GEMINI_API_KEY=...        # never in utux.yaml or a file in the repository
   ```

3. **A small run first**, into its own directory:

   ```bash
   uv run utux gold perturb \
     --imported ~/utux-data/gold/items/scifact --imported ~/utux-data/gold/items/sciclaimeval \
     --parents ~/utux-data/gold/v0-parents/parents.jsonl \
     --method gemini --max-cost-usd 1 --per-type 2 --seed 7 \
     --out ~/utux-data/gold/v0-perturbed-trial
   ```

   Check its `events.jsonl` before the full run:
   - every call is `ok`, with no `error` events;
   - `tokens_out` is at most 2048 on every call, which shows that the output
     limit holds, thinking included;
   - the estimated cost per call is in line with the estimate in the pull
     request.

4. **The full run:**

   ```bash
   uv run utux gold perturb \
     --imported ~/utux-data/gold/items/scifact --imported ~/utux-data/gold/items/sciclaimeval \
     --parents ~/utux-data/gold/v0-parents/parents.jsonl \
     --method gemini --max-cost-usd 5 --per-type 15 --seed 7 \
     --out ~/utux-data/gold/v0-perturbed
   ```

5. **Read the run.** Every call is a `model_call` event in
   `~/utux-data/gold/v0-perturbed/events.jsonl`, with `estimated_cost_usd`, an
   estimate from the table; `cost_usd` stays null, as Gemini reports none.
   The command prints the estimate and the amount counted against the cap.
   A call that could pass the cap is refused (`budget_exhausted`) and the
   run stops.

## 3b. Citation existence items, with OpenAlex

This step makes network calls to OpenAlex, with no key unless
`OPENALEX_API_KEY` is set. SciFact titles of the parents' abstracts are
searched.
- **Accepted** only when exactly one result has the identical normalised
  title. The others are dropped and counted.
- **Items:** each real reference gives a real item and one altered copy:
  title, first author or year, in turn.
- **Requests:** go one at a time, 10 a second, and every call is a
  `literature_call` event in the output's `events.jsonl`.

```bash
uv run utux gold existence-items \
  --scifact ~/utux-data/gold/scifact \
  --release ~/utux-data/gold/v0-parents/parents.jsonl \
  --max-documents 60 --seed 20261123 --out ~/utux-data/gold/v0-existence
```

It writes `existence-items.jsonl`, already split into `dev` and `test` by
real reference, and prints the counts: titles searched, real references,
drops by reason, and items by construction and split.

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
