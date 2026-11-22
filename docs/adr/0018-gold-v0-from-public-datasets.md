# ADR-0018: Gold set v0 from public datasets and perturbations

- Status: Accepted
- Date: 2026-11-22

## Context

RFC-002 plans gold set v0 as about 150 claims labelled by two independent
annotators with graduate-level training and adjudicated by a third (RFC-002,
sections 3 and 5; `docs/plan/M0.md`, M0-15). No human annotators are
available. RFC-002 section 2 names public datasets such as SciFact only as a
secondary, external check, whose labels are not merged into the set because
their label definitions differ from RFC-001. Task M0-15b asks for a proposal
to build v0 from public expert-annotated datasets and from perturbations
whose labels follow from their construction, with a converter and its
counts (`docs/plan/M0.md`, M0-15b).

## Decision

Gold set v0 is built as
[the gold v0 strategy](../eval/gold-v0-strategy.md) describes. Its items are:

- SciFact (`train`, `dev`) and SciClaimEval (`dev`) items, imported by
  `utux gold import-public` with a fixed label mapping and drop rules;
- perturbations whose labels follow from their construction, built later.

Gemini may write perturbations and flag disagreements; it never gives a
reference label and is never the S3 or S5 model in utux. The maintainer
audits 30 items. RFC-002 is amended to match (sections 1 to 7).

## Alternatives rejected

- **Wait for human annotators, as RFC-002 plans.** Not rejected on its merits.
  It is not possible now, and M2 scoring needs a gold set.
- **Labels from a model.** Rejected: RFC-002, principle 1, and AGENTS.md,
  section 8, forbid model-made reference labels.
- **Public datasets only, without perturbations.** Rejected as insufficient:
  neither dataset has `partially_supported` or scope flags, so S4 could not
  be scored (strategy, section 3).

## Consequences

- RFC-002 sections 1 to 7 are amended. The import output stays outside the
  repository; it becomes part of a release only at the v0.1 freeze.
- The imported labels follow other definitions than RFC-001. The differences
  are listed in the strategy, section 3, and stated with every result.
- Scores on imported items may be inflated by contamination; results are
  reported per dataset and origin.
- The licence questions of the strategy, section 2, decide what can be
  stored and released.

### Acceptance, 2026-11-22

Accepted by the maintainer on 2026-11-22, with the decisions recorded in the
strategy, sections 2 to 10:
- **Licences.**
  - SciFact is treated as CC BY-NC 2.0 until AllenAI clarifies, and its
    abstracts are never redistributed.
  - Of SciClaimEval, only CC BY 4.0 and public-domain samples are kept.
  - NC data stays on the maintainer's machine for non-commercial research
    evaluation, and this is revisited if utux is ever offered commercially.
- **Label mapping, evidence spans and drop rules** are approved.
  - S4 is not scored on imported items.
  - SciClaimEval items are excluded from S2.
- **Domain mapping and table rendering** are approved for evaluation only:
  SciClaimEval's `nlp` and `ml` become `ml`, `peerj` becomes `biomedicine`,
  and tables are rendered as text with one paragraph per row. ADR-0014 admits
  abstracts and structured full text for the verifier. This rendering serves
  gold items only and does not extend what the verifier stores.
- **Perturbations** record their confirmation (`deterministic`,
  `model_check` or `audit`).
- **Gemini** is pinned to `gemini-3.8-flash` on the paid tier.
- **Audit:** 30 items, with a kappa below 0.6 triggering a mapping review.
- **Size:** about 300 items.
- **Results:** headline metrics over all items, results per origin
  mandatory, and the H3 thresholds must also hold on the perturbed subset.
- **Item schema:** option (a).
- **Source groups:** SciFact by cited abstract, SciClaimEval by `paper_id`.

RFC-002 is amended to match.

## Sources

- `docs/rfc/RFC-002.md`, sections 1 to 6.
- `docs/plan/M0.md`, M0-15 and M0-15b.
- `docs/eval/gold-v0-strategy.md` and `docs/eval/datasets.md`.
- `docs/adr/0014-source-text-in-m2.md` and
  `docs/adr/0015-shared-passage-splitter.md`.
- AGENTS.md, section 8.
