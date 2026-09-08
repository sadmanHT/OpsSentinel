# Phase 8 Handoff — Controlled Research Experiments and Architecture Comparisons

## Status

**Implementation and research campaign are code-complete; merge closure is still pending.** On branch `phase-8-controlled-research`, code head `f72e47c297e57fc9135c8252af9001fd94f469b4` passed every Phase 8 experiment workflow plus the Phase 6, Phase 7, ResearchLab, and cumulative CI regressions on that exact SHA. PR #10 remains the Phase 8 integration vehicle.

This handoff update is intentionally not a post-merge completion claim. The documentation-inclusive branch head created by closure synchronization must itself remain green, PR #10 must merge with an expected-head guard, and the resulting `main` commit must pass the cumulative Phase 1–8 validation before Phase 8 is fully closed.

## What Phase 8 adds

Phase 8 turns the Phase 7 evaluator into a controlled experimental system for comparing autonomous incident-investigation behavior without treating preferred research outcomes as CI targets.

Implemented behavior includes:

- a standalone typed `researchlab/` package for experiment plans, cells, deterministic trial identities/seeds, resumable campaigns, retained trajectories, typed scores, and descriptive reports;
- one-factor-at-a-time configuration validation across architecture, investigation budget, tool order, evidence/verification mode, temporal reasoning, and compound stopping strategy;
- deterministic public BenchmarkLab scenario references that retain scenario/split/difficulty identity while excluding evaluator-only ground truth from agent runtime;
- durable experiment/evaluation persistence through the canonical PostgreSQL research schema and restart-safe resume without duplicate completed agent runs;
- explicit runtime health/provenance for architecture, temporal reasoning, tool order, evidence mode, stopping strategy, and compound-plan controls;
- fail-closed ResearchLab treatment isolation that rejects configuration/health/provider-marker mismatches before launching a trial;
- reactive ReAct versus explicit-planner runtime architecture variants;
- investigation budgets at 5, 10, 15, and 20 legal tool calls;
- controlled free, deployment-first, symptom-first, and adaptive tool-order treatments over a common legal invocation set;
- passive-only versus deterministic active-verification evidence treatments;
- standard versus explicit cause→effect temporal reasoning using only public incident onset and MCP-returned evidence timestamps;
- a shared ten-step cross-service passive evidence plan for compound incidents plus standard versus unresolved-evidence stopping;
- dedicated clean-stack GitHub Actions campaigns that run real BenchmarkLab → ChaosLab → agent → EvaluationLab → PostgreSQL trajectories, verify fault restoration/log cleanliness, retain raw artifacts, and report performance descriptively rather than thresholding it;
- cumulative regression coverage that keeps Phase 6 BenchmarkLab, Phase 7 EvaluationLab, earlier Phase 8 experiments, and the ordinary Phase 1–8 CI gate green together.

## Research-integrity rules demonstrated

1. **Performance is measured data, not a pass condition.** CI gates execution correctness, treatment isolation, persistence, safety, cleanup, reproducibility, and artifact integrity. Accuracy, evidence quality, latency, and failure rates are reported as observed.
2. **Ground truth remains evaluator-only.** Agent-visible incident payloads exclude BenchmarkLab ground truth, secondary-cause labels, hidden causal timelines, and ChaosLab controller state.
3. **Only the target dimension changes inside a controlled comparison.** ResearchLab validates frozen non-target configuration and runtime provider markers before execution.
4. **Null and negative results are preserved.** No benchmark label, scoring rule, tool ordering, prompt, threshold, or experiment code was changed merely to make a preregistered hypothesis appear true.
5. **Real mechanisms are verified, not inferred from configuration strings.** Runtime health and retained trajectories prove that each treatment actually changed the intended mechanism.
6. **Clean-state/recovery behavior remains part of research validity.** Every live arm starts from an isolated Compose stack, restores ChaosLab faults, checks critical logs, proves resumability, and tears down cleanly.

## Measured Phase 8 findings

These findings come from the validated local Compose provider/model baseline. They are descriptive results for this implementation and dataset, not general claims about other models or production incidents.

### 1. H1 — Planning heterogeneity: reactive ReAct vs explicit planner

Twenty real trials covered two scenarios in each difficulty tier for each architecture.

- Easy, Medium, Hard, and Adversarial: both architectures achieved root-cause accuracy **1.00** and exact-match rate **1.00**.
- Compound: both architectures achieved root-cause accuracy **0.50** and exact-match rate **0.00**.
- Mean tool calls were identical within every difficulty tier.
- Compound failures in both arms retained `COMPOUND_CAUSE_OMISSION`, `MISSED_EVIDENCE`, `TOOL_MISUSE`, and one `OVERCONFIDENCE` classification.

**Interpretation:** null architecture effect on diagnosis in this controlled local baseline. Explicit planning did not solve the compound-secondary-cause weakness and generally added latency rather than diagnostic benefit.

Authoritative current-head artifact: `phase8-h1-planning-difficulty-report`, GitHub artifact digest `sha256:3a7f9f37737191a30e0c72eb1b07c6ccdebf1ffcefd6f5f0bc28538052802453`.

### 2. H2 — Investigation budget: 5 vs 10 vs 15 vs 20 calls

Forty real trials used the full ten-scenario validation cohort at each budget.

Every budget measured the same:

- root-cause accuracy: **0.80**;
- exact-match rate: **0.80**;
- mean tool calls: **2.40**;
- mean confidence: **0.773**;
- budget exhaustion count: **0**;
- no-fault negative-control false positives: **1/1**.

Only budget utilization changed mechanically: approximately 0.48, 0.24, 0.16, and 0.12 for budgets 5, 10, 15, and 20.

**Interpretation:** null budget effect across this range because the agent usually stopped well before even the smallest budget. Increasing the ceiling alone did not cause deeper investigation or improve diagnosis.

Authoritative current-head artifact: `phase8-h2-investigation-budget`, GitHub artifact digest `sha256:76a5878d1710feeba5d40e796730743ef7bac589359cb963881e3a9d15bc0b13`.

### 3. H3 — Temporal reasoning: standard vs explicit cause→effect

Ten real trials covered four misleading-deployment adversarial cases plus the no-fault negative control in both temporal modes.

Both arms measured:

- root-cause accuracy: **0.60**;
- exact-match rate: **0.60**;
- mean confidence: **0.584**;
- mean tool calls: **2.60**;
- false-positive rate on the no-fault control: **1.00**.

The treatment mechanism did change: explicit cause→effect produced a mean **0.60** temporally stamped hypotheses versus **0.00** for standard reasoning, with **0** temporal-order violations. Diagnostic outcomes did not change.

**Interpretation:** valid null diagnostic effect. Explicit temporal representation changed the intended reasoning metadata without changing RCA on this cohort.

Authoritative current-head artifact: `phase8-h3-temporal-reasoning-report`, GitHub artifact digest `sha256:1b693518fe8ce6822660e6c5762a05fd13b87e847afd33e42aa9a9c3bae2279f`.

### 4. Controlled tool order: free vs deployment-first vs symptom-first vs adaptive

Forty real trials used ten validation scenarios across four order treatments over a common legal invocation set.

All four arms measured:

- root-cause accuracy: **0.80**;
- exact-match rate: **0.80**;
- adversarial RCA/exact match: **0.6667**;
- mean confidence: **0.773**;
- no-fault negative-control false positives: **1/1**.

The order treatment itself was real and visible in trajectories. Deployment-first began with `inspect_deployment` in all ten cases and increased mean tool calls to **3.60** versus **2.80** for free, symptom-first, and adaptive. It did not improve diagnosis.

**Interpretation:** null diagnostic order effect with measurable deployment-first investigation overhead.

Authoritative current-head artifact: `phase8-tool-order-report`, GitHub artifact digest `sha256:b8a71006ec82204aadc16ce94e01ccbf81a29707aac1846d062f8e2e2705725a`.

### 5. H4 — Passive evidence vs active verification

Twenty real trials compared passive-only and verification-enabled evidence collection across the ten-scenario validation cohort.

Both arms measured:

- root-cause accuracy: **0.80**;
- exact-match rate: **0.80**;
- evidence precision: **0.80**;
- evidence recall: **0.75**;
- critical-evidence recall: **0.75**;
- mean confidence: **0.773**;
- no-fault negative-control false positives: **1/1**.

Verification executed exactly one deterministic verification probe per trial, increasing mean tool calls from **2.40** to **3.40** and mean latency from roughly **0.57 s** to **1.16 s**, without changing diagnosis, evidence metrics, or confidence.

**Interpretation:** valid null diagnostic/calibration effect with clear verification cost in this baseline.

Authoritative current-head artifact: `phase8-passive-verification-report`, GitHub artifact digest `sha256:a78ff7577c15d1f83990fcf28d9cae0a97ab10ba56d7b2c85c64b219a540bd72`.

### 6. H5 — Compound stopping: confidence threshold vs unresolved evidence

Sixteen real hidden-test trials covered all eight compound scenarios under the same fixed ten-step cross-service passive investigation plan. Only the stopping rule changed.

Standard confidence-threshold arm:

- root-cause accuracy: **0.75**;
- exact-match rate: **0.00**;
- mean completed required steps: **4.75/10**;
- full-plan completion rate: **0.00**;
- mean evidence recall: **0.40625**;
- mean multi-root-cause precision: **1.00**;
- mean multi-root-cause recall: **0.50**;
- mean secondary recall: **0.00**;
- mean tool calls: **4.75**;
- mean latency: about **0.92 s**.

Unresolved-evidence arm:

- root-cause accuracy: **0.50**;
- exact-match rate: **0.00**;
- mean completed required steps: **10/10**;
- full-plan completion rate: **1.00**;
- mean evidence recall: **0.4375**;
- mean multi-root-cause precision: **1.00**;
- mean multi-root-cause recall: **0.50**;
- mean secondary recall: **0.00**;
- mean tool calls: **10.00**;
- mean latency: about **1.42 s**.

The unresolved-evidence mechanism therefore worked exactly as intended operationally: it forced every required observation to complete. It still failed to recover any secondary root cause and reduced primary RCA on two paired scenarios while improving aggregate evidence recall only slightly.

**Interpretation:** negative treatment effect. Forcing unresolved-evidence completion increased work and evidence collection but did not improve compound completeness and reduced primary diagnostic accuracy from 0.75 to 0.50. This result is preserved unchanged.

Authoritative current-head artifact: `phase8-compound-handling-report`, artifact ID `10044523422`, GitHub artifact digest `sha256:cbe11f54db258c48b2627f60c24fd4dfc719fa7d760e540df33ba1764262496b`.

## Cross-experiment findings

The combined local-baseline evidence does **not** support a simple “more reasoning is better” story:

- explicit planning did not outperform reactive execution;
- larger tool-call ceilings did not make the agent investigate more deeply;
- explicit temporal structure changed hypothesis metadata but not diagnoses;
- forced deployment-first ordering added work without improving accuracy;
- one active verification probe per case added latency/calls without changing correctness or confidence;
- forcing full compound evidence collection increased work substantially and made primary RCA worse while secondary recall remained zero.

The strongest persistent weakness is not raw access to more observations. It is **evidence interpretation and multi-cause diagnosis**, especially distinguishing/retaining secondary causes and correctly recognizing a no-fault state.

## Known non-blocking limitations and negative findings

- **No-fault behavior remains weak.** The validation negative control repeatedly produced `inconclusive` instead of `no_fault`, yielding a false positive/miss under the evaluator in H2, H3, Tool Order, and H4. This was not hidden or relabeled.
- **Compound secondary recall remains zero in H5.** Full-plan execution alone did not solve multi-cause reasoning.
- **Current comparisons use the local deterministic-evidence provider/model baseline.** These findings are not population estimates across external LLMs or real production incidents.
- **Recorded comparative cost is zero in the current local provider.** Tool calls and latency therefore carry more information about investigation overhead than monetary cost in these campaigns.
- **Sample sizes are controlled engineering/research cohorts rather than statistical claims about all incidents.** Phase 8 reports descriptive paired results and does not manufacture significance claims.

## Defects found and repaired during Phase 8 validation

Validation failures were treated as blocking engineering defects without weakening research assertions:

- temporal experiments initially exposed a clock-domain mismatch between synthetic BenchmarkLab incident onset timestamps and runtime ChaosLab telemetry; H3 introduced a treatment-neutral runtime public-onset normalization while leaving evaluator truth unchanged;
- H3 integrity initially failed Ruff before experiments could run; the lint defects were fixed and no H3 treatment executed until the integrity gate was green;
- controlled tool-order design initially risked comparing different tool availability rather than ordering; all four arms were changed to receive the same legal invocation set before order-only treatment;
- H5 initially inherited the validation split even though all compound scenarios are hidden-test; the preregistered plan was corrected to `hidden_test` before live interpretation;
- H5 report run #2 failed after both valid live arms because its reporting environment omitted the EvaluationLab package; only the reporting dependency was repaired, the SHA advanced, and the full exact-head H5 plus cumulative chain was rerun rather than reusing stale successful arms.

## Code-complete exact-head validation

On code head `f72e47c297e57fc9135c8252af9001fd94f469b4`, every required workflow completed successfully:

- Phase 6 BenchmarkLab **#182**, run `34197407149`: PASS;
- Phase 7 EvaluationLab **#187**, run `34197407144`: PASS;
- Phase 8 ResearchLab **#188**, run `34197407143`: PASS;
- Phase 8 H3 Temporal Reasoning **#107**, run `34197407141`: PASS;
- Phase 8 Tool Order **#68**, run `34197407150`: PASS;
- Phase 8 Passive vs Verification **#38**, run `34197407199`: PASS;
- Phase 8 Compound Handling **#4**, run `34197407145`: PASS;
- cumulative CI **#247**, run `34197407161`: PASS.

This exact-head chain includes static/unit/integrity checks, strict typing, real clean-stack treatment arms, artifact reporting, persistence/resume checks, fault restoration, log inspection, Phase 6/7 regressions, and the ordinary cumulative Phase 1–8 CI gate.

## Required closure sequence

Phase 8 is ready for the final closure sequence, but no later phase should rely on it until all steps pass:

1. this documentation/README closure synchronization is committed to PR #10;
2. the new documentation-inclusive PR head passes the relevant Phase 6/7/8 workflows and cumulative CI on that exact SHA;
3. PR #10 is marked ready for review only after that proof;
4. PR #10 merges using an expected-head guard so GitHub cannot merge a different unvalidated SHA;
5. the resulting `main` merge commit passes push-triggered cumulative Phase 1–8 validation;
6. only then is Phase 8 fully closed and available as a prerequisite for the next gated phase.

## Guarantees available after full closure

After the post-merge `main` proof passes, later phases may rely on:

- controlled, deterministic, resumable research campaigns over real agent trajectories;
- explicit runtime treatment provenance and fail-closed isolation;
- evaluator-only hidden truth and ground-truth-free agent inputs;
- six validated research comparison surfaces: architecture, budget, tool order, verification, temporal reasoning, and compound stopping;
- raw trajectory and report artifacts that preserve null/negative findings;
- cumulative clean-state validation through Phase 8.
