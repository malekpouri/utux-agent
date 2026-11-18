# utux Agent — Technical Product Specification

Nov 15, 2026 · @Alan Baghumian

## 1. Overview

utux Agent is an open-source, modular multi-agent framework that takes a computational research project from idea to reviewed manuscript, with every scientific claim traceable to a source or a computed result.

It targets three problems in current research-agent systems:

- **Reliability.** Generated papers contain unsupported claims, fabricated or mismatched citations, and numbers that do not match the code output.
- **Cost.** A single strong model is used for every task, including trivial ones.
- **Fragmentation.** Ideation, literature review, experiments and writing live in separate tools with no shared record.

The design is a small fixed core with pluggable layers. Stages exchange files, not in-memory objects, so each stage can be run, replaced, inspected or edited by hand.

**Positioning.** utux Agent is an independent framework, complementary to [Denario](https://pypi.org/project/denario/0.1.25/). Denario is the reference point for comparison and evaluation. As a project decision, no Denario code is reused: Denario is GPLv3, utux Agent is Apache-2.0, and keeping the code bases separate avoids licensing questions. This is a project choice, not a legal conclusion about what GPLv3 permits. Project migration from Denario is out of scope for v1.

- Repository: [github.com/malekpouri/utux-agent](https://github.com/malekpouri/utux-agent)
- Project site: [utux.ir](https://utux.ir)

### Scientific contribution

The contribution is a verifiable, evidence-grounded multi-agent framework for computational scientific research. Reliability, cost and integration are product goals; the research claims are narrower and testable:

1. A method for building and validating a claim ledger that links every scientific claim to checked evidence or a computed result.
2. A multi-step method for checking evidence and detecting unsupported, contradicted and fabricated claims.
3. An empirical evaluation of how these mechanisms, model routing and reproducible execution affect scientific correctness, cost and reproducibility.

### Hypotheses

The evaluation is designed before the system is built. Each hypothesis names the experiment that can refute it (section 11). Thresholds are fixed in the evaluation protocol before any system output is scored, and locked as RFC-002 section 8 states.

| # | Hypothesis | Tested by | Refuted if |
| --- | --- | --- | --- |
| H1 | Verification reduces unsupported claims, invalid citations and wrong numbers in the final output | Multi-agent with and without verification | Error rates on the gold set do not drop |
| H2 | Model routing lowers cost without lowering reliability | Routing against a single strong model on the same tasks | Cost does not fall, or error rates rise |
| H3 | The verification checks detect planted errors with useful precision and recall | Gold set with planted errors | Any of the five thresholds of RFC-002 section 8 is missed: false-verified rate, critical miss rate, verified coverage, macro-F1 of status, review load |
| H4 | Run manifests make results reproducible within a stated tolerance | `reproduce.sh` on a clean machine | Results fall outside tolerance |
| H5 | The full system is more reliable than Denario at comparable cost | Controlled comparison | No difference, or worse, on the reliability metrics |

### What is new

A reviewer will ask why this is more than LangGraph, several models and retrieval combined. The answer has to come from the experiments. The table states design intent only; each row needs evidence from section 11 before it appears in a paper.

| Capability | General multi-agent systems | utux Agent (design intent) |
| --- | --- | --- |
| Content produced by several agents | Usually yes | Yes |
| Model cost management | Depends on the system | Tiered routing with budgets |
| Claim linked to specific evidence | To be evaluated | Core mechanism: claim ledger |
| Citation validity check | To be evaluated | Part of verification |
| Numbers matched to experiment results | To be evaluated | Structured result records |
| Provenance of every claim | To be evaluated | Claim ledger and event log |
| Experiment reproduction | Depends on the system | Run manifest and `reproduce.sh` |
| Independent detection of scientific errors | To be evaluated | Reviewer agents and benchmark |

## 2. Goals, non-goals and success metrics

### Goals

1. **Scientific reliability.** Reduce hallucinated claims, citations and numbers. Every claim in an output links to a verified source or a computed artifact.
2. **Lower cost.** Route each task to the cheapest model that can do it, and escalate only on failure.
3. **One environment.** Cover ideation, literature review, methodology, implementation, experiments, writing and review in a single project workspace.

### Non-goals for v1

- Wet-lab experiments and field work.
- Medical diagnosis and clinical decision-making.
- Automatic submission of papers to journals.
- Any guarantee of acceptance or novelty.
- Bulk generation of papers without scientific validation.
- Unattended execution of high-risk biological operations.
- Web dashboard, multi-user server deployment, fully offline mode, Persian-language manuscripts. The architecture must not block these later.

### Success metrics

| Metric | How it is measured |
| --- | --- |
| Citation validity | Share of cited references that resolve to a real record with matching metadata |
| Claim support | Share of literature claims judged supported by the cited source |
| Numeric traceability | Share of numbers in the manuscript that match a value in a results artifact |
| Reproducibility | Share of runs whose results are regenerated by `reproduce.sh` within tolerance |
| Cost and time | USD and wall-clock time per completed project, against a single-strong-model baseline |
| Comparison with Denario | Same tasks, same model budget, same metrics as above |
| Adoption | Researchers outside the team completing a real project with the tool |
| Publication | A paper on the architecture and its empirical evaluation |

**How the metrics are measured.** Each reliability metric is computed against a gold-standard evaluation set with reference answers (section 11), not against the system's own judgement. Detection metrics are reported as precision, recall, F1 and false-positive rate. Human grading follows a written rubric and is done by evaluators who are independent of the development team.

## 3. Users, entry modes and outputs

**Primary users** are academic researchers, graduate and PhD students, and research teams. v1 assumes a technical user who is comfortable with Linux, Python, the command line and Docker. A graphical interface comes later.

**Language.** Interface, documentation and manuscripts are English in v1. Persian documentation and Persian manuscripts are later additions.

### Entry modes

A project can start from any of three inputs, alone or combined:

| Entry mode | User provides | Pipeline starts at |
| --- | --- | --- |
| Question | A research question or topic | Ideation |
| Hypothesis | An initial idea or hypothesis | Literature review, to test novelty |
| Data | Personal datasets and research files, with a description | Ideation, constrained by the data |

A user can also supply any intermediate file by hand, for example their own methodology, and run only the later stages.

### Outputs

- Research proposal
- Literature review
- Technical report
- Experimental results: code, logs, figures, run manifests
- Scientific manuscript in LaTeX or Markdown
- Review report and verification report, attached to every manuscript

## 4. v1 scope: the six pipeline stages

v1 covers computational research only: data analysis, simulation, algorithm development and machine learning. Each stage reads the files of earlier stages and writes its own.

| # | Stage | What it does | Main output | Approval gate (default mode) |
| --- | --- | --- | --- | --- |
| 1 | Research ideation | Generates several candidate ideas, critiques and ranks them, checks feasibility against available data and tools | `idea.md` | Approve or edit the idea |
| 2 | Literature review | Searches sources, summarizes, scores novelty, builds a gap table | `literature.md`, `references.bib` | None; loops back to stage 1 if the idea is not novel |
| 3 | Methodology design | Writes a step-by-step plan with a success criterion, cost and time estimate per step | `method.md` | Approve or edit the method |
| 4 | Implementation | Writes code for each step and smoke-tests it on a small sample | `code/` | None |
| 5 | Experiment and analysis | Runs the full experiments in the sandbox, records manifests, analyses results | `results.md`, `figures/`, `runs/` | Approve the experiment plan before full execution |
| 6 | Scientific writing and review | Builds the claim ledger, writes from it, runs verification and independent review | `paper/`, `review.md`, `verification.md` | Approve the final manuscript; always on |

Review findings are routed back to the stage that caused them. A wrong number goes back to stage 5, not to the writer. Each loop has a retry cap and a budget cap.

## 5. Architecture

The core knows nothing about any research domain. Everything domain-specific lives in a domain pack, and everything replaceable sits behind one of six interfaces.

&#91;embedded content: utux Agent architecture · interfaces, workspace, fixed core, six plug-in points, domain pack\]

User interfaces and the core meet only in the project workspace files. The core calls out through six interfaces, and the domain pack decides which implementation sits behind each one.

### Fixed core

- The six-stage workflow graph, checkpoints and approval gates.
- Budget manager, retry caps and model router.
- Project workspace format, claim ledger and event log (section 7).
- Verification engine and provenance recorder (section 8).

Two things are deliberately not pluggable: the orchestration engine and the project state format. Making either one swappable would couple every module to the abstraction.

### Six pluggable interfaces

Each interface is a Python `Protocol`. Implementations are separate packages discovered through entry points.

| Interface | Problem it solves | Contract | v1 implementations | Status in v1 | Reason for the status |
| --- | --- | --- | --- | --- | --- |
| `ModelProvider` | Users have different providers, budgets and access, and models change often | `complete(request) -> response`; the request carries a model already chosen by the core's router, and the response carries usage and cost | OpenRouter, a direct OpenAI key and local OpenAI-compatible servers such as Ollama, through one OpenAI-compatible client in the core (ADR-0008) | Public | Many models and providers |
| `LiteratureSource` | Each field has its own databases | `search()`, `fetch()`, `resolve(identifier)` | OpenAlex, arXiv, Semantic Scholar, PubMed through BioMCP; several can be active at once | Public | Many scientific sources, and new ones per field |
| `ToolProvider` | Domain tools cannot be hard-coded into a general core | Lists and calls domain tools | MCP client; any MCP server is added by configuration | Public | Connects MCP servers and specialised tools |
| `Executor` | Compute differs: laptop, GPU workstation, cluster | `run(step) -> artifacts` (code, logs, figures, manifest) | Local Docker sandbox | Internal | Docker is the only real implementation so far |
| `Writer` | Venues and report types need different formats | `render(claims, sections, figures, refs)` | LaTeX, Markdown | Internal | LaTeX and Markdown are enough for now |
| `Reviewer` | Review depth trades off against cost | `review(paper, code, ledger) -> issues` | Single independent reviewer, three-reviewer panel | Internal | One stable implementation comes first |

Every implementation must pass a shared conformance test suite for its interface.

Every public interface is a contract that must be kept, even before it has outside users. v1 therefore commits to three public APIs, not six. An internal interface becomes public only when two independent implementations pass its conformance tests.

Internal does not mean loosely designed. `Executor`, `Writer` and `Reviewer` have the same clean, typed contracts and conformance tests as the public interfaces, and the core reaches them only through those contracts. When a second implementation arrives, each can be made public without wide changes to the core.

### Domain packs

A domain pack is a directory with one configuration file. Adding a field means adding a pack, not changing the core.

```yaml
domain: ml
literature: [openalex, arxiv, semantic_scholar]
tools: []                      # MCP servers, e.g. mcp://biomcp in a bio pack
executor: docker
image: utux/ml:latest          # Python scientific stack + PyTorch, scikit-learn
prompts: ./prompts/
rubric: ./review_rubric.md
template: ./latex/
```

v1 ships three packs. `generic` is the baseline and `ml` is the team's main test domain. `bio-pilot` is a deliberately thin slice that validates the general core on a specialised field from the start:

- PubMed and NCBI access through BioMCP.
- Search for related papers; fetch and store metadata and abstracts.
- Claim-to-evidence checking on the retrieved passages.
- One simple ML experiment on a public biomedical dataset.

The full `bio` pack follows after v1.

### Profiles

A profile is a named combination of implementations. Only profiles are tested in CI; other combinations are community-supported.

| Profile | Models | Executor | Purpose |
| --- | --- | --- | --- |
| `default` | OpenRouter | Local Docker | Recommended starting point |
| `local` | Ollama | Local Docker | No API cost; lower quality on planning and coding |

### Future-proofing

- **Web dashboard.** The core only writes events and approval requests to files. A dashboard is a separate package that reads them.
- **Multi-user.** A project directory is self-contained, with no global state. Every event carries an `actor` field.
- **Other executors.** cmbagent, a cloud sandbox or an HPC cluster are added as `Executor` packages without touching the core.

## 6. Technology stack

Python 3.12+ is the implementation language. The table lists the v1 default for each layer and what is deferred. Versions, pricing and rate limits of third-party tools must be re-checked at implementation time.

| Layer | v1 default | Also supported in v1 | Deferred |
| --- | --- | --- | --- |
| Orchestration | LangGraph, validated by the M1 spike below | None; fixed layer | None |
| Model access | OpenRouter through a small OpenAI-compatible client in the core | Direct OpenAI key and local OpenAI-compatible servers such as Ollama, through the same client | Direct Anthropic and Gemini keys, through an optional provider package |
| Literature | OpenAlex, arXiv | Semantic Scholar; PubMed and NCBI through BioMCP in the bio pilot | PaperQA2 for full-text Q&A |
| Citation resolution | Crossref, with OpenAlex and arXiv as fallbacks | None | None |
| Domain tools | MCP client with permission manifests | Any MCP server by configuration | Curated server list per pack |
| Code execution | Hardened Docker sandbox with a Jupyter kernel (section 10) | NVIDIA GPU passthrough when detected | Remote executor over SSH or Slurm; cloud sandbox; cmbagent |
| Experiment tracking | Run manifest and structured result records per run, plus git | None | MLflow export |
| Writing | LaTeX compiled with Tectonic | Markdown through Pandoc | Journal templates as plugins; Typst |
| Review | One reviewer on a different model from the writer | Three-reviewer panel with a meta-reviewer | Reproducibility reviewer |
| State | Project files with metadata sidecars, plus SQLite checkpoints | None; fixed layer | Postgres for server deployments |
| Interface | CLI built with Typer | None | Web dashboard as a separate package |
| Observability | Local JSONL event log | Langfuse | OpenTelemetry export; hash-chained log |
| Packaging | `uv` with lock files, entry points for plugins, one Docker image with LaTeX | None | Pack template generator |

### Recommendations added to the initial proposal

- **Model access without LiteLLM.** Models are reached through one small OpenAI-compatible client in the core, for the reasons recorded in ADR-0008.
- **ML pack first, thin bio pilot alongside.** The main test domain is machine learning, so OpenAlex, arXiv and Semantic Scholar are the first literature sources. BioMCP and PubMed enter v1 only through the bio pilot pack (section 5).
- **Pydantic schemas** for every file contract in section 7, so agents and humans get the same validation errors.
- **One git repository per project.** Each stage completion is a commit. Rollback, diff and branching two methods from one idea come for free.
- **GPU and remote compute.** v1 runs on a Linux laptop with 16 GB RAM and no dedicated GPU. The executor uses a GPU when present. Heavy jobs move to a remote executor after v1.

### Prototype evaluation for LangGraph

Build stages 3 to 5 as a spike and confirm four things: resume after a crash from the SQLite checkpoint, pause and resume at an approval gate, a review finding routed back to an earlier stage, and a run that streams events to the log. If any of these needs heavy workarounds, fall back to a plain Python state machine with the same file contracts.

## 7. Data contracts

Files are the only interface between stages, and between the core and any user interface. Every file below has a versioned Pydantic schema.

### Project directory

```text
my-project/
  utux.yaml                 # [init]  profile, domain pack, budget, oversight mode, data policy
  .gitignore                # [init]  checkpoints, temporary files, caches
  inputs/                   # [init]  user question, hypothesis, data description, data files
  idea.md                   # [later]
  literature.md             # [later]
  references.bib            # [later]
  sources/                  # [init]  one file per source: metadata, passages, URL, licence, retrieval date
  method.md                 # [later]
  code/                     # [init]
  runs/                     # [init]
  runs/<run_id>/            # [later] manifest.json, logs, outputs
  results.jsonl             # [init]  structured result records; empty at first
  figures/                  # [init]
  results.md                # [later]
  claims.jsonl              # [init]  claim ledger; empty at first
  paper/                    # [init]  LaTeX or Markdown sources, compiled PDF
  review.md                 # [later]
  verification.md           # [later]
  events.jsonl              # [init]  append-only event log; starts with the project_created event
  approvals/                # [init]  pending and answered approval requests
  .utux/meta/               # [init]  one metadata sidecar per artifact version
  .utux/checkpoints.sqlite  # [later]
  reproduce.sh              # [later]
```

Paths marked `[init]` exist after `utux init`. Paths marked `[later]` are created by the stage or component that owns them. A directory that is empty after `utux init` holds a `.gitkeep` file, so that the first commit contains the whole tree.

### Artifact metadata and validity

Every stage output has a metadata sidecar, so the system always knows what an output was built from. A sidecar is stored as `.utux/meta/<artifact_id>.json`.

```json
{"artifact_id": "method-v003", "stage": "methodology", "schema_version": 1,
 "created_by": "agent:methodologist", "created_at": "2026-11-15T10:00:00Z",
 "input_artifacts": ["idea-v002", "literature-v004"],
 "content_hash": "sha256:...", "state": "valid"}
```

| Situation | Behaviour |
| --- | --- |
| A user edits an upstream file after later stages ran, for example `method.md` after the experiments | The content hash changes and every artifact built from the old version is marked `stale`. Stale results cannot back a verified claim until the stage is re-run, or the user explicitly re-accepts them, which is logged |
| The schema version changes | Each schema has a version and a migration function. `utux migrate` upgrades old projects; the core refuses to run on an unmigrated project rather than guess |
| A stage stops halfway | Outputs are written to a temporary directory and moved into place only when the stage completes. An artifact without a completed sidecar is ignored |
| Two agents want to change the same file | Each artifact has one owning stage. Inside a stage, parallel agents return proposals and a single writer commits the file |
| Dependency tracking | `input_artifacts` records the exact versions consumed, so the chain from manuscript back to inputs can be rebuilt |

### Claim ledger

One line per atomic scientific claim. The writer may only use claims whose status is `verified`, or other claims that the user has explicitly accepted at a gate.

```json
{"schema_version": 1, "id": "C017", "type": "result", "kind": "quantitative",
 "text": "The proposed scheduler reduces validation loss by 4.2% relative to the baseline on dataset X.",
 "span": {"file": "results.md", "start": 812, "end": 904},
 "status": "verified", "confidence": "high", "needs_human": false,
 "reasons": [],
 "evidence": [{"evidence_type": "result_record", "id": "R0042"}],
 "verified_by": ["numeric_check@1"],
 "check_id": "k-000101", "trace": "verification/C017/k-000101.json",
 "claim_hash": "sha256:...", "checked_at": "2026-11-15T10:58:12Z",
 "human": null}
```

| Status | Meaning |
| --- | --- |
| `verified` | Direct and sufficient evidence was found in the text or artifact that was checked |
| `partially_supported` | Part of the claim is supported, or support holds only under narrower conditions than stated |
| `contradicted` | The evidence conflicts with the claim |
| `insufficient_evidence` | The available evidence does not settle the claim, or two checkers disagree |
| `unverified` | Not yet checked |

`verified` means supported by the evidence that was checked. It does not mean the claim has been proven scientifically true.

- `type` is `literature`, `result` or `derived`.
- The fields of a ledger entry are those of RFC-001, section 6, for every claim type.
- Each evidence entry has an `evidence_type`. A `literature` claim takes only `source` entries: the entry of RFC-001, section 6, with the source identifier (DOI, arXiv ID, PMID), the supporting passage and `checked_text`, which is `abstract` or `full_text`. A `result` claim takes only `result_record` entries, each the id of a result record. A `derived` claim takes only `claim` entries, each the id of a claim it follows from.

### Result records

A number is never stored bare. Each computed value is a structured record in `results.jsonl`, so its meaning is checked along with its value.

```json
{"schema_version": 1, "id": "R0042", "metric": "AUC", "value": 0.95, "unit": "score",
 "dataset": "dataset_x", "model": "model_a", "split": "test",
 "run_id": "r012", "source": "runs/r012/metrics.json", "tolerance": 0.005}
```

Every number in a manuscript has a source type, and each type is checked against its own source:

| Source type | Checked against |
| --- | --- |
| `artifact` | A result record |
| `literature` | The cited source passage |
| `config` | The experiment configuration in the run manifest |
| `dataset` | The dataset description and computed data statistics |

### Run manifest

`runs/<run_id>/manifest.json` records:

- The command, the full experiment parameters and the configuration files.
- The git commit, and whether the working tree had uncommitted changes.
- The container image digest and locked package versions.
- The dataset version, how it was obtained, and input data hashes.
- Random seeds.
- Hardware, plus CUDA and driver versions when a GPU is used.
- Model versions and inference settings, for runs that call models.
- Versions of any external API or service the run depends on.
- Start and end time, and exit status.

`reproduce.sh` replays the manifests in order. Two levels are distinguished. Exact reproducibility, meaning identical output, is expected only for deterministic CPU runs. Reproducibility within tolerance applies to GPU and parallel runs, where the same seed does not guarantee identical numbers. Each result record carries its accepted tolerance.

### Event log

`events.jsonl` is append-only and is the public interface for dashboards and audit.

```json
{"schema_version": 1, "event_id": "e-000913", "run_id": "p-7f3a", "request_id": "q-0412", "parent_id": "e-000907",
 "ts": "2026-11-15T10:42:07Z", "actor": "agent:planner", "stage": "methodology",
 "type": "model_call", "model": "<model id>", "prompt_version": "planner@3", "tool_version": null,
 "input_hash": "sha256:...", "output_hash": "sha256:...",
 "tokens_in": 5120, "tokens_out": 830, "cost_usd": 0.012, "duration_ms": 8400,
 "status": "ok", "status_reason": null, "retry_reason": null, "escalated_from": null,
 "data": {"provider": "openrouter", "is_external": true}, "artifacts": ["method-v003"]}
```

Event types include stage start and end, model call, tool call, code execution, verification result, approval requested, approval answered, budget warning, setting changed and error. `retry_reason` and `escalated_from` record why a call was repeated or moved to a stronger tier.

`status` is `ok`, `error` or `refused`. A refused action is one that utux itself declined, for example a call to an external provider under `local_only` or a call after the budget is exhausted. `status_reason` is a stable machine code that explains any status other than `ok`, such as `model_timeout` or `budget_exhausted`; it is null exactly when the status is `ok`. Free-text error messages are not stored.

`data` holds the details that are specific to an event type, as a flat object of scalar values with documented keys per type. A `setting_changed` event, for example, carries the setting's key and its old and new values, and a `model_call` event carries the name of the provider and whether it is external, so the log shows which provider received which content hash. A `budget_warning` event carries `spent_usd`, the known cost so far, and `total_usd`, the budget it was compared with. Message content and source text never go into `data`.

An incomplete last line left by an interrupted write is never repaired automatically. `utux log repair` moves the fragment to a side file, restores the log to its last complete event and records the repair as an event.

Append-only is enforced by the application, not by the file system, so the log is not tamper-proof. Hash chaining, where each event stores the hash of the previous one, is planned after v1 to make later edits detectable.

### Approvals

The core writes `approvals/<id>.request.json` and pauses. The CLI, or any future interface, writes `approvals/<id>.response.json` with `approve`, `reject` or `edit` and, for an edit, the id and content hash of the edited version the person saved. Responses are written atomically: temporary file, then rename.

## 8. Reliability design

Scientific reliability is the core of the design and of the evaluation, not an added feature. Eight mechanisms are in v1; two are deferred.

| Mechanism | What it does in v1 |
| --- | --- |
| Evidence-grounded generation | Agents write literature statements only from fetched passages stored in `sources/`, never from model memory |
| Claim-level citations | Every sentence with a factual claim in the manuscript carries a claim ID that maps to the ledger |
| Scientific claim verification | Four checks, listed below, set each claim's status |
| Reproducible experiment tracking | Run manifests, pinned container images, seeds and data hashes; `reproduce.sh` |
| Independent reviewer agent | Runs on a different model from the writer and sees only the paper, code and ledger, not the generation history; it re-fetches evidence itself instead of trusting stored passages |
| Human-in-the-loop approval | Gates at idea, method, experiment plan and final manuscript (section 9) |
| Provenance and audit trail | `events.jsonl` plus git history record every decision, source and setting change |
| Reliability benchmark | A fixed task suite scored on the metrics in section 2 (section 11) |

### Verification checks

1. **Citation existence.** Each reference is resolved by DOI, arXiv ID or PMID against Crossref, OpenAlex, arXiv or PubMed. Title, authors and year must match. Unresolved references are removed from the bibliography and their claims are marked `unverified`.
2. **Citation support.** A model that judges support can itself be wrong, for example by accepting a claim that the source makes only for one dataset, one metric or one experimental condition. The check therefore has six steps:
   1. Extract atomic claims from the text.
   2. Identify the source and the exact location of the evidence.
   3. Check semantic agreement between the claim and the evidence.
   4. Check conditions, limitations and scope: dataset, metric, population and experimental setting.
   5. Have a second model from a different family assess the claim independently. Disagreement sets the status to `insufficient_evidence` and flags the claim at the human gate.
   6. Record status, confidence and which text was checked in the claim ledger.
3. **Numeric traceability.** A deterministic checker matches every number in the manuscript to its source by source type (section 7). For computed results it compares metric, dataset, model, split and unit as well as the value, so 0.95 accuracy cannot stand in for 0.95 AUC, and a relative change cannot stand in for an absolute one. Mismatches beyond the record's tolerance block the manuscript. A verified result claim has confidence high; any other result claim has low. A derived claim is verified only if every parent claim is verified, and its confidence is the lowest confidence among its parents.
4. **Internal consistency.** The same quantity must agree across text, tables and figures. All three are generated from the same result record, and the checker confirms it.

The results are written to `verification.md` and attached to every output.

### Verification toggle

Verification is on by default and can be switched off in `utux.yaml`. Switching it off is logged as a `setting_changed` event, and the output carries a visible `verification disabled` note in `verification.md`. The audit trail cannot be switched off.

### Deferred

- **Pre-registration.** Lock hypothesis, success criteria and statistical tests before execution, and have the reviewer check deviations.
- **Reproducibility reviewer.** An independent agent re-runs the code from scratch and compares the numbers.

## 9. Human oversight, model routing and cost control

### Oversight modes

Human-in-the-loop is the default. The mode is set per project in `utux.yaml`.

| Mode | Idea | Method | Experiment plan | Final manuscript |
| --- | --- | --- | --- | --- |
| `guided` (default) | Approve | Approve | Approve | Approve |
| `auto` | Automatic | Automatic | Automatic | Approve |

- At every gate the user can approve, reject with feedback, or edit the file directly.
- The final manuscript gate is always on, in every mode.
- A budget or retry cap being reached pauses the run and asks the user, in every mode.
- Low-risk tasks such as searching, summarizing and formatting never need approval.
- Individual gates can be switched on or off; each change is logged.

### Model routing

Each agent role maps to a tier, and each tier maps to a model in the profile. The user changes models in one place.

| Tier | Used for | Selection rule |
| --- | --- | --- |
| `light` | Summaries, extraction, formatting, query rewriting | Cheapest model that passes the role's conformance tests |
| `standard` | Drafting, routine code, literature synthesis | Mid-priced model |
| `strong` | Planning, methodology, debugging, review | Best available model |

- **Escalation.** A task starts at its role's tier. If a deterministic check or a reviewer rejects the output, it is retried one tier up.
- **Reviewer independence.** The reviewer's model must come from a different model family than the writer's.
- **Caching.** Model responses are cached by input hash, so re-running an unchanged step costs nothing.

### Role-based model selection

Three fixed tiers are the v1 starting point. Model quality differs by task: a cheap model can be strong at extraction and weak at methodology. From M4, the model for each role is chosen by measured performance on that role's benchmark, not by price or size alone.

| Role | Selection criterion |
| --- | --- |
| Literature search and extraction | Extraction accuracy and coverage |
| Scientific reasoning | Quality of argument and hypothesis critique, graded by rubric |
| Coding | Code correctness and test pass rate |
| Data analysis | Correct calculations and correct interpretation of results |
| Writing | Writing quality and preservation of claim IDs and citations |
| Reviewer | Error detection rate and false-alarm rate on planted errors |

A different model family does not by itself make the reviewer independent. The reviewer also has no access to the generation history and bases its assessment on evidence it retrieves itself (section 8).

### Cost control

- Each project has a total budget and a per-stage budget in USD. The total budget has no default: the user states it when the project is created with utux init. Per-stage budgets are optional, and none may exceed the total.
- The CLI prints a cost estimate before each stage and the running total after it.
- Every model call logs tokens and cost to `events.jsonl`.
- Literature results and source passages are cached across projects on the same machine.

* The CLI reports estimated and actual cost for every stage and every agent role.

## 10. Security, misuse prevention and AI disclosure

### Execution security

Docker alone is not a complete security boundary, so the sandbox is hardened in depth.

- Model-written code runs only inside the sandbox. There is no host-execution option in v1.
- The container runs as a non-root user, with rootless Docker where available.
- Each run has CPU, memory, wall-clock, disk and process-count limits, configurable in `utux.yaml`.
- The root filesystem is read-only. Only the run's output directory is writable, and input data is mounted read-only.
- No privileged mode, no host devices, all Linux capabilities dropped, `no-new-privileges` set, and a seccomp profile enabled. GPU passthrough is the only device exception.
- Only the needed project subdirectories are mounted. The home directory and the Docker socket are never mounted.
- Network access is off by default, with an allowlist for package registries and declared data sources. Every connection is logged.
- API keys never enter the sandbox, the event log or any output file.

### MCP servers and plugins

First-use confirmation is not enough. Each MCP server and plugin has a permission manifest that states which tools it exposes, which file paths it may read or write, which network hosts it may reach, and which credentials it receives.

- The CLI shows the manifest for approval before the server is enabled, and again whenever the manifest changes.
- The core enforces the manifest where it can: a tool allowlist per agent, and path and network restrictions for servers run in containers.
- Every tool call is logged with its arguments hash and result hash.
- Tool output is treated as untrusted data and never as instructions to an agent.

### Misuse prevention

| Risk | Control |
| --- | --- |
| Bulk paper generation without evidence | No batch mode for manuscripts; one project produces one manuscript; the final gate needs a human |
| Fabricated references | Citation existence check; unresolved references are removed |
| Unsupported claims | Claim ledger; the writer uses only verified or explicitly accepted claims |
| Unvalidated results | Numeric traceability check blocks the manuscript on mismatch |
| Untraceable decisions | Append-only event log and git history for every agent decision and source |
| Unattended high-risk tasks | Code execution and experiment runs need plan approval in `guided` mode; budget caps in every mode |

These controls raise the cost of misuse. They do not make it impossible, because the code is open source and can be modified.

### Data confidentiality

- Each project declares a data policy in `utux.yaml`: `external_allowed` or `local_only`.
- Under `local_only`, raw data and text derived from it go only to local models. External models see schemas and aggregate statistics that the user has approved.
- The event log records which provider received which content hash.
- The documentation tells users to check provider retention terms and their institution's rules before using personal, clinical or unpublished data.

### AI-use disclosure

- The system drafts a disclosure statement from the event log: which stages used AI, which models, and what the human approved or edited.
- The statement is never added automatically. The author reviews, edits and approves it at the final gate.
- Drafting the statement can be switched off in `utux.yaml`.
- The documentation states that outputs are drafts that need expert review, and that authors are responsible for the disclosure rules of their venue.

## 11. Evaluation

The evaluation is designed first. Hypotheses H1 to H5 in section 1 fix what is measured, and the system is built against tests that can refute them. The benchmark is also the regression suite for development and the empirical basis of the paper.

### Gold-standard evaluation set

Reference answers are created independently of the system, so every reported score has a defined ground truth.

| Item type | What it tests |
| --- | --- |
| Claims with valid supporting evidence | False-positive rate of the support check |
| Claims with no support in the cited source | Detection of unsupported claims |
| Claims the source contradicts, or supports only under narrower conditions | Detection of contradiction and scope errors |
| Fabricated or mismatched references | Citation existence check |
| Wrong numbers, and correct numbers attached to the wrong metric, dataset or split | Numeric traceability |
| Methodological errors in experiment design, such as test-set leakage | Reviewer agents |

Each check is scored with precision, recall, F1 and false-positive rate. Items are labelled by two annotators using a written guideline, and their agreement is reported.

### Task suite

| Task type | Example | What a correct outcome looks like |
| --- | --- | --- |
| Reproduction | Re-derive a published result on a small public dataset | Numbers within tolerance of the published values |
| Data-driven analysis | A provided tabular dataset with a planted effect | The effect is found and correctly quantified |
| Negative control | A dataset with shuffled labels | The system reports no effect instead of inventing one |
| Literature-only | A review on a narrow, well-covered topic | Citations exist and support the claims |
| Specialised pilot | Bio pilot: a PubMed literature question plus a simple ML experiment on a public biomedical dataset | Citations exist and support the claims; the result reproduces |

General ML tasks use small public datasets that run on CPU. The specific datasets and papers are selected at the start of M4.

### System configurations

The same tasks run under six configurations, so each improvement can be attributed to one component.

| Configuration | What it isolates |
| --- | --- |
| Single strong model | Baseline |
| Multi-agent without verification or routing | Effect of the multi-agent structure alone |
| Multi-agent with verification | Effect of evidence checking (H1) |
| Multi-agent with model routing | Effect of routing on cost and quality (H2) |
| Multi-agent with all mechanisms | The complete system |
| Denario | An existing research framework (H5) |

A same-model reviewer variant runs as one extra ablation.

### Denario comparison protocol

- Pin and report the exact Denario version and the workflow that is compared.
- Use the same underlying models and the same token or USD budget for both systems.
- Give both systems the same literature and search access. Where tool access differs, report it and also run utux Agent restricted to matching tools.
- Score all outputs with the same external checkers and the same blind human graders.
- Report all runs, their variance and their failures, not only the best cases.

### Metrics

The reliability metrics of section 2, plus cost, wall-clock time, the number of human interventions per run, and the share of reviewer findings confirmed by a human expert.

### Human evaluation

Graders are researchers in the field who did not develop the system. They grade blind to which system produced an output and follow a written scoring rubric. Inter-rater agreement is reported.

### Agent-level tests

Each agent has its own test set in addition to the end-to-end pipeline tests, and the per-role scores feed model selection (section 9). Reviewer agents are tested on manuscripts with planted errors. The detection rate and false-alarm rate per error type are published, so users know what the reviewer misses.

### Bias checks

The benchmark reports source concentration, meaning the share of citations from a few venues, groups or years. It also reports whether contrary evidence was retrieved, and whether the interpretation of results goes beyond what the numbers support.

## 12. Roadmap

No deadline is set, so milestones are ordered by dependency and each has an exit criterion. The evaluation protocol comes first, then the hardest parts: execution and verification.

| Milestone | Scope | Exit criterion |
| --- | --- | --- |
| M0. Foundations and evaluation protocol | Repository layout, file schemas, event log, CLI skeleton, `ModelProvider` with OpenRouter. Written hypotheses, metric definitions, thresholds, and gold set v0 | `utux init` creates a valid project; a model call is logged with cost; the protocol is committed before any system output is scored |
| M1. Execution spike | Stages 3 to 5 on LangGraph with the hardened Docker executor, run manifests and result records | The four LangGraph checks in section 6 pass; the orchestration choice is confirmed |
| M2. Verification | Claim ledger, the four verification checks, `LiteratureSource` with OpenAlex and arXiv, PubMed through BioMCP | Verification is scored on gold set v0 with precision, recall and F1 |
| M3. Full pipeline | Stages 1, 2 and 6, approval gates, tier routing, independent reviewer, artifact metadata and staleness | One ML task and the bio pilot task each run from question to reviewed PDF in `guided` mode |
| M4. Benchmark | Full gold set, task suite, six configurations, per-role model benchmark, Denario comparison | One command produces a report that covers H1 to H5 |
| M5. v1 release | `generic`, `ml` and `bio-pilot` packs, documentation, Docker image, conformance tests, security review of the sandbox, landing page on utux.ir | An outside researcher completes a project from the documentation alone |
| M6. Paper | Architecture and empirical evaluation | Manuscript submitted |

### After v1

- Web dashboard as a separate package.
- Full bio pack; further domain packs.
- Remote and cloud executors; cmbagent as an executor plugin for comparison.
- Pre-registration and the reproducibility reviewer.
- Review-only mode: the user supplies a paper and code, and only verification and review run.
- Hash-chained event log.
- Server deployment for teams; Persian documentation and manuscripts; fully offline profile hardening.

## 13. Licensing, community, decisions and risks

### Licensing and community

- **License.** Apache-2.0 for the core and first-party packs. A license audit of all dependencies runs before the first public release to confirm compatibility.
- **Copyleft isolation.** Any dependency with a copyleft license lives in its own optional plugin package, never in the core.
- **Business model.** None in the first phase. A hosted version or organizational services are possible later.
- **Contributions.** Outside contributors are welcome on the core, agents, scientific tools and domain packs. Stable, versioned interfaces and the conformance tests are the precondition.
- **Team.** The founder and a consulting engineer, with the final team size open. API spend is pay-as-you-go through OpenRouter and kept low by routing and free data sources.

### Decisions

All seven decisions below were accepted on 15 Nov 2026. The last column lists the work that remains for each.

| Decision | Outcome | Remaining work |
| --- | --- | --- |
| Orchestration engine | LangGraph | The M1 spike validates it; a plain Python state machine is the fallback only if the spike fails |
| License | Apache-2.0 | Dependency license audit before the first public release |
| Benchmark tasks | Small public ML datasets that run on CPU | Select the specific datasets and papers at the start of M4 |
| Default models per tier | Chosen by benchmark cost and quality, not fixed in the spec | Run the selection in M3 and record it in the `default` profile |
| Claim extraction granularity | Sentence level, with a manual override | Implement in M2 |
| Full-text access for claim support | Abstracts plus open-access full text only | Implement in M2; label which text was checked |
| Docker image distribution | One base image plus one image per domain pack | Build and publish in M5 |

Three further decisions were added after the team review on 15 Nov 2026: a thin `bio-pilot` pack is in v1 scope; an interface becomes public plugin API only after two implementations pass its conformance tests; and the evaluation protocol is written in M0, before the system is built.

### Risks

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Modularity adds complexity without user benefit | Slower delivery, more bugs | Two fixed layers, two profiles, conformance tests; add options only on real demand |
| Output quality no better than Denario | No reason to adopt | Lead with reliability metrics and the benchmark; ship review-only mode early |
| Claim support checked against abstracts only | False confidence in citations | Label which text was checked; report the limitation in `verification.md` |
| Small team | Slow progress | Strict v1 scope; execution and verification first |
| API cost during development | Budget overrun | Response caching, light-tier models for tests, CPU-sized benchmark tasks |
| Reviewer agents miss errors | Wrong results pass | Deterministic checks first; reviewer calibration; mandatory human final gate |
| Third-party API changes | Broken sources or models | Interfaces isolate each provider; conformance tests run in CI |

Risks added after the team review:

| Risk | Effect | Mitigation |
| --- | --- | --- |
| The model-based support check is itself wrong | Claims marked `verified` that the source does not support | Six-step check with scope analysis and a second model; precision and recall reported on the gold set; confidence recorded; human gate |
| The bio pilot widens v1 scope | Delay to the core | Keep it thin: literature, evidence checking and one experiment; no bio tooling beyond BioMCP |
| Sandbox escape or a malicious plugin | Damage to the user's machine or data | Hardened container, permission manifests, security review before release |
| Benchmark built by the developers favours the system | Results that do not convince reviewers | Protocol fixed in M0, independent annotators and graders, all runs reported |

## 14. Cross-cutting requirements

| Topic | Requirement |
| --- | --- |
| Confidential data | Per-project data policy that controls what may be sent to external services (section 10) |
| Resource limits | CPU, memory, GPU, time and disk limits per run, set in `utux.yaml` (section 10) |
| Error handling | API outage: retry with backoff, then another provider in the same tier, then pause with state checkpointed. MCP failure: the tool is marked unavailable, the agent is told, and the gap is recorded. Docker failure: the run is marked failed with logs and never silently skipped. No failure path may produce a claim |
| Prompt management | Prompts are versioned files in the domain pack. Every model call logs the prompt version and hash. A prompt change re-runs that agent's tests |
| Agent evaluation | A test set per agent, in addition to end-to-end pipeline tests (section 11) |
| Scientific sources | Each source records its URL, identifier, licence or access terms, retrieval date, version, extraction method and extraction quality. Full text is stored only where the licence allows |
| Bias control | Bias checks in the benchmark (section 11). The reviewer rubric asks for contrary evidence and alternative explanations |
| Invalid data | Stage 5 starts with data validation: missing values, duplicates, train-test leakage, and label or schema inconsistencies. Findings are shown at the experiment-plan gate |
| Dependencies | Lock files for the core and for each pack image, pinned image digests, and automated vulnerability scanning in CI |
| Cost | Estimated and actual cost per stage and per agent role (section 9) |
