# Phase 7 Handoff — Evaluation Engine, Calibration, and Failure Taxonomy

## Status

**Closure record.** Phase 7 implementation, documentation-inclusive branch validation, exact-head PR #9 merge, and post-merge `main` cumulative validation have all passed. PR #9 merged validated head `84a486bc78c75c9e5c26bd7bf7a4c1128041b2cf` into `main` at `a8c699948aafd3342439f9933190a8f0f9e10a80`, and push-triggered CI **#153** passed the complete Phase 1–7 gate on that merge commit. This status-only documentation update changes no implementation; project policy still requires the CI triggered by this exact final status commit to remain green before Phase 8 work starts.

## Implementation summary

Phase 7 adds the scientific measurement layer required to evaluate saved OpsSentinel benchmark trajectories automatically, reproducibly, and without manual spreadsheet calculations.

Implemented behavior includes:

- a standalone typed `evaluationlab/` package with strict Pydantic contracts for evaluation cases, RCA/compound metrics, evidence quality, tool-call utility, efficiency, safety, calibration bins, aggregate evaluations, counterfactual observations, and failure classifications;
- deterministic adaptation of saved BenchmarkLab scenarios and `BenchmarkRunArtifact` trajectories into evaluator inputs without rerunning or modifying the agent trajectory;
- root-cause scoring for primary correctness, secondary-cause recall, multi-root-cause precision/recall, and exact match;
- evidence precision/recall, critical evidence recall, and distractor-selection scoring derived from persisted tool provenance;
- investigation-efficiency metrics for useful evidence per tool call, duplicate calls, irrelevant calls, failed calls, misleading calls, total calls, and steps to the first observable non-rejected correct hypothesis;
- marginal-evidence utility labels for discriminative, repeated, irrelevant, and misleading tool calls;
- confidence calibration through Brier score, expected calibration error, reliability bins, and deterministic SVG reliability diagrams;
- safety scoring for unsafe attempts, blocked destructive requests, unnecessary approvals, and incorrectly classified risk;
- deterministic failure taxonomy with the complete initial Phase 7 vocabulary and at least one classification for every incorrect diagnosis;
- controlled counterfactual scoring for pairwise consistency, causal sensitivity, and causal invariance;
- typed persistence/readback through the canonical `evaluation_runs`, `evaluation_scores`, and `experiment_metadata` tables;
- family-scoped counterfactual score persistence under `counterfactual:<family>` while preserving separate ordinary evaluation runs for every real agent trajectory;
- real PostgreSQL integration validation that applies migrations from zero, persists evaluation output, disposes/reopens the engine, requires exact typed readback, and verifies migration rollback/re-upgrade;
- a live BenchmarkLab → autonomous agent → EvaluationLab → PostgreSQL → restart/readback smoke;
- a five-tier live representative matrix covering Easy, Medium, Hard, Adversarial, and Compound scenarios while treating diagnostic performance as measured data rather than a CI target;
- a four-variant live `deploy-cron-latency` counterfactual experiment including the fault-free `no_fault` control;
- reproducible JSON research summaries and a reliability SVG uploaded from cumulative CI;
- dedicated Phase 7 static/persistence CI plus integration into the ordinary clean-state cumulative Phase 1–7 Compose gate.

## Important design decisions

1. **Evaluation consumes saved trajectories.** EvaluationLab scores the persisted benchmark/agent record; it does not ask the agent to restate or regenerate its reasoning during scoring.
2. **Research performance is data, not a pass threshold.** CI gates evaluator correctness, execution integrity, persistence, and safety. RCA accuracy, calibration, counterfactual scores, and failure rates are reported exactly as measured.
3. **Ground truth remains evaluator-only.** Expected RCA labels and benchmark metadata never cross into the agent-visible incident request.
4. **Evidence scoring uses provenance.** Evidence tags are derived from persisted tool references and structured payloads rather than treating free-form model reasoning as evidence.
5. **Compound incidents retain partial-credit structure.** Correct primary RCA with a missed secondary cause is not scored as an exact match.
6. **Calibration is computed automatically.** Brier, ECE, reliability bins, and the reliability diagram come from the same typed evaluation cases rather than manual post-processing.
7. **Failure classification is deterministic.** Observable trajectory signals map to explicit categories; incorrect runs always receive at least one category through a deterministic fallback.
8. **`ANCHORING` is not fabricated from weak proxies.** The category exists in the typed vocabulary, but current saved trajectories do not prove that an initial hypothesis persisted despite contradictory evidence. Distractor capture and premature convergence remain separate categories rather than being relabeled as anchoring without evidence.
9. **Counterfactual consistency is separate from ordinary correctness.** A family may respond causally to an intervention even when one individual diagnosis is wrong; Phase 7 stores both measurements instead of collapsing them into one score.
10. **Counterfactual aggregates reuse the canonical score table.** Family metrics use the synthetic scenario scope `counterfactual:<family>` with `agent_run_id = NULL`; variant evaluations remain linked to their real agent-run UUIDs.
11. **Live experiment provenance records the actual provider/model.** Compose runs use the configured local provider/model identity rather than being mislabeled as deterministic merely because the evaluator itself is deterministic.
12. **Phase 7 remains cumulative.** The ordinary CI workflow executes all accumulated Phase 2–7 live smokes from a clean Compose environment before restart cleanup and teardown.

## Defects found and repaired during validation

Phase 7 validation exposed real integration/provenance issues that were repaired without weakening scientific assertions:

- **PostgreSQL FK fixture ordering:** the integration fixture initially added an incident and agent run in one pending flush without ORM relationship metadata, allowing SQLAlchemy to flush the agent row before its referenced incident. The fixture now flushes the incident first, preserving the production FK and proving the intended persistence path rather than weakening constraints.
- **live experiment provenance label:** the first live evaluation smoke labeled the Compose run as `deterministic` even though the deployed backend used the local provider/model defaults. The smoke now records the actual configured provider/model (`local` / `local-placeholder` by default, with environment overrides) while preserving the scenario seed/version.
- **counterfactual durability gap:** the existing counterfactual scorer initially produced only in-memory metrics. Phase 7 added typed family-metric persistence plus real PostgreSQL restart/readback so causal measurements are durable research records rather than ephemeral CI output.

Mechanical Ruff import-order failures were fixed exactly as reported; lint configuration, tests, and research assertions were not relaxed.

## Migrations and configuration

No new Phase 7 database migration is required. The canonical backend schema already contains `evaluation_runs`, `evaluation_scores`, and `experiment_metadata`; Phase 7 adds typed EvaluationLab storage/readback behavior against those tables.

New project configuration/CI surface includes:

- standalone `evaluationlab/pyproject.toml`;
- dedicated `.github/workflows/phase7-evaluationlab.yml` with Ruff, strict mypy, known-answer tests, deterministic scoring smoke, migrations-from-zero, PostgreSQL persistence/restart readback, and rollback/re-upgrade;
- ordinary `.github/workflows/ci.yml` installs EvaluationLab in the Compose job and executes the Phase 7 live smokes after the existing Phase 2–6 chain;
- CI research artifact output under `artifacts/phase7/`.

Live evaluation provenance supports:

- `OPSSENTINEL_EVALUATION_PROVIDER`;
- `OPSSENTINEL_EVALUATION_MODEL`;
- `OPSSENTINEL_PHASE7_ARTIFACT_DIR`;
- the existing `OPSSENTINEL_DATABASE_URL`.

## Validation commands and gates

Phase 7 static/known-answer validation:

```bash
python -m pip install -e 'evaluationlab[dev]'
ruff check evaluationlab scripts/phase7-evaluation-smoke.py \
  scripts/phase7-representative-evaluation-smoke.py \
  scripts/phase7-counterfactual-evaluation-smoke.py
mypy evaluationlab/evaluationlab
pytest evaluationlab/tests
```

PostgreSQL persistence/restart validation after backend migrations:

```bash
pytest evaluationlab/integration/test_postgres_persistence.py
```

The dedicated workflow also runs:

```bash
cd backend
alembic upgrade head
alembic downgrade base
alembic upgrade head
```

Clean-state cumulative Phase 1–7 Compose sequence includes:

```bash
python scripts/phase2-smoke.py
python scripts/phase3-mcp-smoke.py
python scripts/phase4-agent-smoke.py
python scripts/phase5-operational-smoke.py
python scripts/phase5-approval-negative-smoke.py
python scripts/phase5-rejected-matrix-smoke.py
python scripts/phase6-benchmark-smoke.py
python scripts/phase7-evaluation-smoke.py
python scripts/phase7-representative-evaluation-smoke.py
python scripts/phase7-counterfactual-evaluation-smoke.py
```

The cumulative gate also verifies clean startup, expected schema state, persisted checkpoint/diagnosis/evaluation/experiment rows, normal load generation, metrics/tool/agent endpoints, zero residual ChaosLab faults, critical-log absence, restart cleanup, artifact upload, and clean teardown.

## Validation results

### Live evaluator/persistence foundation

After repairing the PostgreSQL fixture ordering issue, head `e315b85b...` established the first fully green Phase 7 package/persistence checkpoint: static evaluator checks, migrations from zero, PostgreSQL restart/readback, rollback/re-upgrade, Phase 6 regression, and cumulative CI all passed.

### First live Phase 7 end-to-end checkpoint

On head `29235f44...`:

- Phase 7 EvaluationLab workflow **#68: PASS**;
- Phase 6 BenchmarkLab regression workflow: **PASS**;
- cumulative CI **#139: PASS**;
- the clean-state Compose gate proved real BenchmarkLab scenario launch → real autonomous agent → EvaluationLab scoring → same Compose PostgreSQL persistence → SQLAlchemy engine disposal/reopen → exact typed readback;
- restart cleanup and teardown also passed.

### Five-tier representative checkpoint

On head `0fe71ff8911389d34f0a6e9d6874224eef071018`:

- Phase 7 EvaluationLab **#76: PASS**;
- Phase 6 BenchmarkLab **#80: PASS**;
- cumulative CI **#143: PASS**;
- Easy, Medium, Hard, Adversarial, and Compound live runs each produced a persisted evaluation record;
- the aggregate JSON summary and reliability SVG were uploaded as CI research artifacts.

### Counterfactual persistence checkpoint

On head `e9290656a181705ec827ad4bd0f0b3a54c29a44d`:

- Phase 7 EvaluationLab **#80: PASS**;
- family-scoped counterfactual metrics survived real PostgreSQL engine restart/readback with exact typed reconstruction;
- all three metric rows were present: consistency, causal sensitivity, and causal invariance.

### Code-complete Phase 7 cumulative checkpoint

On head `9af9f157783afccc34b18b767494edaf59298b77`:

- Phase 7 EvaluationLab **#86: PASS**;
- Phase 6 BenchmarkLab **#85: PASS**;
- cumulative CI **#148: PASS** across backend, ChaosLab, BenchmarkLab, frontend, and Compose;
- clean-state Compose integration gate: PASS;
- Phase 7 research artifact upload: PASS;
- restart cleanup regression: PASS;
- teardown: PASS.

### Documentation-inclusive branch proof

On head `84a486bc78c75c9e5c26bd7bf7a4c1128041b2cf`:

- Phase 7 EvaluationLab **#94: PASS**;
- Phase 6 BenchmarkLab **#89: PASS**;
- cumulative CI **#152: PASS**;
- documentation, handoff, EvaluationLab static/persistence checks, the clean-state Phase 1–7 Compose gate, research artifact upload, restart cleanup, and teardown all passed together on the exact PR head.

### Merge and post-merge `main` proof

- PR **#9** merged the exact validated head `84a486bc78c75c9e5c26bd7bf7a4c1128041b2cf` using an expected-head guard;
- merge commit: `a8c699948aafd3342439f9933190a8f0f9e10a80`;
- push-triggered `main` CI **#153: PASS**;
- backend: PASS — Ruff, strict mypy, unit tests, startup/import smoke, migration upgrade, integration tests, migration rollback/re-upgrade;
- ChaosLab: PASS — Ruff, unit tests, import smoke;
- BenchmarkLab: PASS — Ruff, strict mypy, unit/integrity tests, catalog smoke;
- frontend: PASS — production build;
- Compose: PASS — validation/build, complete clean-state Phase 1–7 integration gate, Phase 7 research artifact upload, restart cleanup, and teardown.

The documentation-inclusive branch head and merged `main` are therefore both substantively validated. This final status-only commit changes documentation status records only and must retain green CI as the last mechanical safeguard.

## Measured research findings from the validated local baseline

These are observations from the validated local Compose provider/model baseline, not required targets and not general claims about other models.

### Five-tier representative matrix

The selected live representatives measured:

- exact-match rate: **0.80**;
- primary root-cause accuracy: **1.00**;
- evidence precision: **0.50**;
- evidence recall: **0.45**;
- critical evidence recall: **0.45**;
- useful evidence per tool call: **0.6667**;
- Brier score: **0.1889**;
- expected calibration error: **0.17**;
- unsafe action attempts: **0**;
- incorrectly classified risk: **0**.

Easy, Medium, Hard, and Adversarial representatives were exact matches. The Compound representative found the correct primary cause but omitted the secondary cause and was classified with `COMPOUND_CAUSE_OMISSION`, `MISSED_EVIDENCE`, `TOOL_MISUSE`, and `OVERCONFIDENCE`.

This five-case matrix is a representative engineering/research smoke, not an estimate of full-benchmark population performance.

### Four-variant `deploy-cron-latency` counterfactual family

Measured family scores were:

- consistency: **1.00**;
- causal sensitivity: **1.00**;
- causal invariance: **1.00**;
- pair count: **6**;
- all six pairwise relationships consistent.

The three faulted variants were correctly diagnosed as `database_connection_leak` at 0.96 confidence. The fault-free `deploy_cron_disabled` control expected `no_fault` but produced `inconclusive`, so its ordinary exact-match result was false and it received `MISSED_EVIDENCE` and `TOOL_MISUSE` classifications.

The perfect family causal scores therefore do **not** mean every variant was diagnostically correct. They mean prediction-change behavior matched the controlled causal intervention structure. Preserving both measurements is an intentional Phase 7 research-integrity property.

## Phase 7 required behavior demonstrated

- known-answer synthetic predictions return designed metric values;
- RCA, compound, evidence, efficiency, calibration, safety, and failure-taxonomy computations are automatic and typed;
- evaluating the same saved case is deterministic;
- reliability bins and diagrams are generated programmatically;
- every incorrect diagnosis receives at least one failure classification;
- the complete initial failure-category vocabulary is available without inventing unsupported anchoring labels;
- evaluator truth remains isolated from the agent request;
- evaluation metadata, scores, traces, experiment configuration, dataset version, and failure categories persist in PostgreSQL;
- persistence survives engine restart/readback;
- controlled counterfactual families produce durable consistency/sensitivity/invariance measurements;
- live evaluation runs preserve actual scenario version, seed, tool budget, architecture identity, and provider/model provenance;
- representative live validation spans every difficulty tier;
- the counterfactual no-fault control is measured rather than coerced into a preferred result;
- the complete Phase 1–7 system passes together from a clean Compose environment on the documentation-complete branch head and on post-merge `main`.

## Known non-blocking limitations

- **Anchoring observability:** `ANCHORING` is part of the typed taxonomy, but the current saved trajectory contract does not expose a sufficiently trustworthy signal for automatic anchoring detection. Phase 7 intentionally does not conflate distractor capture or premature convergence with anchoring. A later phase may add explicit initial-hypothesis persistence/contradiction observability.
- **Representative matrix size:** the five-tier live matrix uses one deterministic representative per tier. Its aggregate values validate the research pipeline but are not statistically representative full-benchmark estimates. Phase 8 is the appropriate layer for controlled multi-run architecture/model comparisons.
- **Local baseline scope:** measured values above come from the current local Compose provider/model baseline. They are not claims about production incidents or other model providers.
- **No-fault behavior:** the controlled no-fault variant produced `inconclusive` rather than `no_fault`. This is retained as a valid negative finding; it is not an evaluator defect and was not hidden by modifying labels or thresholds.
- **Cost comparison:** Phase 7 records the scientific evaluation foundation and investigation-efficiency metrics; comparative cost/latency/model experiments belong to Phase 8.

## Exact Phase 8 prerequisites

Phase 8 may rely on the following **only after** the CI triggered by this final status-only commit remains green:

- the validated 50-scenario BenchmarkLab catalog, seeds, structural splits, and evaluator-only ground truth;
- reproducible saved `BenchmarkRunArtifact` trajectories from real agent executions;
- deterministic `adapt_benchmark_artifact()` conversion into typed evaluation cases;
- deterministic root-cause, compound-cause, evidence, efficiency, calibration, safety, and failure-taxonomy scoring;
- typed `CounterfactualObservation` and family consistency/sensitivity/invariance scoring;
- programmatic reliability-bin and SVG generation;
- durable PostgreSQL evaluation runs, metric rows, experiment configuration, traces, failure categories, and counterfactual family metrics;
- exact restart/readback behavior for persisted evaluation records;
- provider/model, architecture, scenario, dataset, seed, and budget provenance fields suitable for controlled comparisons;
- CI-generated JSON/SVG research artifacts;
- a cumulative clean-state gate that validates Phases 1–7 together without imposing preferred research-performance thresholds.

Phase 8 must not reinterpret the Phase 7 local-baseline measurements as hypotheses already proven; `docs/research-hypotheses.md` remains the pre-registered hypothesis source.

## Final closeout condition

All substantive Phase 7 closeout conditions have passed: implementation, known-answer metric coverage, deterministic evaluation, PostgreSQL persistence/restart readback, representative five-tier live evaluation, controlled live counterfactual evaluation, safety scoring, failure taxonomy, research artifact generation, clean-state cumulative validation, documentation-inclusive branch proof, guarded PR merge, and post-merge `main` validation. The only remaining mechanical safeguard is that the automatically triggered CI for this exact status-only documentation commit must remain green. Once it does, **Phase 7 is fully closed and Phase 8 is unblocked.**
