# OpsSentinel: Evaluating When More Agent Reasoning Helps Incident Diagnosis

## Abstract

OpsSentinel is an experimental autonomous incident-response platform built to study a practical question: **when does additional agent reasoning improve production-incident diagnosis, and when does it instead add latency, tool use, anchoring, overconfidence, or incomplete conclusions?**

The system combines a reproducible microservice fault simulator, a LangGraph-based investigation agent behind a constrained MCP tool boundary, a frozen 50-scenario BenchmarkLab release, deterministic EvaluationLab scoring, controlled ResearchLab experiments, durable cost/latency accounting, distributed tracing, research dashboards, and a human approval interface.

Across controlled Phase 8 experiments, explicit planning, larger investigation ceilings, explicit temporal metadata, forced deployment-first ordering, and one deterministic active-verification probe did not improve diagnosis on their sampled cohorts. Several treatments increased work or latency. Forcing complete compound evidence collection raised investigation effort from 4.75 to 10 tool calls on average but reduced primary RCA accuracy from 0.75 to 0.50 while secondary-cause recall remained zero.

The final preregistered Phase 10 hidden evaluation produced **0.80 primary RCA accuracy but only 0.20 exact complete-diagnosis accuracy**. The two adversarial hidden cases were solved exactly, while all eight compound cases omitted the expected secondary cause. Compound primary accuracy remained 0.75, compound secondary recall was 0.00, critical-evidence recall was 0.475, Brier score was 0.56501, and expected calibration error was 0.573. Six incomplete compound diagnoses were issued at 0.96–0.99 confidence. All ten operational runs completed, no tool call failed, no budget was exhausted, and unsafe action attempts remained zero.

The evidence therefore does not support a simple “more reasoning is better” claim. The strongest persistent limitation is **interpreting evidence into a complete multi-cause explanation and calibrating confidence to diagnosis completeness**, not merely obtaining permission to call more tools.

## 1. Research question

Modern incident-response agents can plan, search logs, inspect metrics, query deployments, reproduce requests, verify actions, and continue investigating after a plausible explanation appears. Those capabilities create an implicit assumption that additional reasoning or investigation should improve reliability.

OpsSentinel tests that assumption directly. Its primary research question is:

> When does additional autonomous investigation improve incident diagnosis, and when does it create wasted effort, anchoring, false positives, overconfidence, or incomplete causal explanations?

The project treats engineering correctness and research success separately. A workflow fails if software isolation, safety, persistence, reproducibility, privacy, cleanup, or artifact integrity fails. A workflow does **not** fail merely because RCA accuracy is low or a hypothesis is rejected.

## 2. System

OpsSentinel is organized as four cooperating systems.

1. **ChaosLab** provides deterministic microservice incidents and modular fault injection. Hidden simulator state and causal labels remain outside the agent runtime.
2. **Agent Runtime** uses LangGraph to maintain a persisted plan, hypotheses, evidence, tool history, budgets, diagnosis, approval state, and verification state. Investigation tools are constrained by an MCP safety boundary.
3. **Benchmark & Evaluation Laboratory** supplies versioned scenarios, split isolation, hidden ground truth, deterministic RCA/evidence/efficiency/calibration/safety metrics, failure taxonomy, persistence, and counterfactual scoring.
4. **Research & Observability Layer** runs controlled experiments and records tokens, provider cost, tool effort, latency, traces, metrics, dashboards, Langfuse observations, and human approval interactions.

The React Incident Console exposes the public incident and agent state while keeping benchmark truth, fault-controller state, and evaluator-only labels out of the browser path.

## 3. Benchmark

OpsSentinel Benchmark v1.0 (`1.0.0`) is frozen at 50 scenarios:

- 30 development;
- 10 validation;
- 10 hidden test;
- 10 easy;
- 12 medium;
- 12 hard;
- 8 adversarial;
- 8 compound.

Scenario definitions, ground truth, split definitions, and EvaluationLab metric implementations are content-pinned by `benchmarklab/release/opssentinel-benchmark-v1.0.json`. `benchmarklab.release.verify_release_freeze()` recomputes the protected Git blob identities from local bytes and fails closed if the research contract changes.

The hidden split is intentionally structurally difficult: two adversarial scenarios and eight compound scenarios. It should not be interpreted as an estimate of the incident distribution of a typical production environment.

## 4. Metrics

EvaluationLab separates several concepts that are often collapsed into one accuracy number.

- **Primary RCA accuracy**: was the main root cause correct?
- **Exact match**: did the complete primary/secondary diagnosis match?
- **Evidence precision/recall** and **critical-evidence recall**.
- **Tool efficiency**: total, irrelevant, duplicate, misleading, and failed calls plus useful evidence per call.
- **Calibration**: Brier score, reliability bins, expected calibration error.
- **Safety**: unsafe attempts, blocked destructive requests, unnecessary approvals, and risk misclassification.
- **Failure taxonomy**: missed evidence, distractor capture, tool misuse/failure, over-investigation, compound omission, temporal failure, unsupported assertion, overconfidence, budget exhaustion, and premature convergence.

Phase 9 adds provider/model execution accounting, tool/model latency, retrieval depth, time to first investigation step, time to diagnosis, time to verified resolution, tokens, and provider-estimated cost. Missing values remain null. A deterministic local provider may truthfully report zero tokens and zero cost.

## 5. Controlled experiments

### 5.1 Planning architecture

Reactive ReAct and explicit-planner variants were compared across difficulty tiers. Both reached 1.00 RCA/exact match on easy, medium, hard, and adversarial samples and 0.50 primary RCA / 0.00 exact match on compound samples. Mean tool calls were equal within each tier.

**Finding:** explicit planning produced a null diagnostic effect and did not solve compound secondary-cause omission.

### 5.2 Investigation budget

Tool-call ceilings of 5, 10, 15, and 20 were tested on the validation cohort. All four settings produced 0.80 RCA, 0.80 exact match, 2.40 mean tool calls, no budget exhaustion, and the same no-fault-control miss.

**Finding:** increasing the maximum budget did not cause deeper investigation because the agent usually stopped before the smallest limit.

### 5.3 Temporal reasoning

Standard reasoning and explicit cause→effect metadata both produced 0.60 RCA/exact match and 2.60 mean tool calls. The explicit treatment correctly changed temporal-hypothesis metadata without changing diagnosis.

**Finding:** a real treatment mechanism can have a null outcome effect.

### 5.4 Tool ordering

Free, deployment-first, symptom-first, and adaptive ordering all produced 0.80 overall RCA/exact match and 0.6667 adversarial RCA. Deployment-first increased mean tool calls to 3.60 versus 2.80 for the other arms.

**Finding:** forcing deployment-first behavior added work without improving diagnosis.

### 5.5 Active verification

Passive evidence and one deterministic active-verification probe both produced 0.80 RCA/exact match, 0.80 evidence precision, 0.75 evidence recall, and 0.773 mean confidence. Verification increased mean calls from 2.40 to 3.40 and latency from roughly 0.57 s to 1.16 s.

**Finding:** verification added measurable cost but no sampled diagnostic or calibration benefit.

### 5.6 Compound stopping

Eight hidden compound scenarios were compared under confidence-threshold stopping and a forced unresolved-evidence plan.

Confidence threshold:

- primary RCA: 0.75;
- exact match: 0.00;
- mean required steps/tool calls: 4.75;
- evidence recall: 0.40625;
- secondary recall: 0.00.

Forced unresolved evidence:

- primary RCA: 0.50;
- exact match: 0.00;
- mean required steps/tool calls: 10.00;
- evidence recall: 0.4375;
- secondary recall: 0.00.

**Finding:** forcing the complete investigation plan increased work and slightly increased evidence recall but reduced primary RCA and recovered no secondary causes.

## 6. Phase 9 cost/observability findings

Phase 9 measured an 80-trial sampled Pareto campaign across tool budget, planning strategy, retrieval depth, and verification strategy. The model dimension remained fixed to the deterministic local provider, so no cross-model optimization claim is made.

Four frontier configurations achieved 0.80 mean RCA/exact match with 2.4 mean tool calls and 2.4 mean retrieved evidence. Verification-enabled configurations used 3.4 calls/retrieved evidence without improving the best accuracy and two verification arms measured 0.70 accuracy.

The project also measured live latency, distributed OpenTelemetry, Prometheus/Grafana views, self-hosted Langfuse traces/scores, the Incident Console, and a persisted EvaluationLab-backed experiment dashboard. A representative real-browser run across easy, hard, adversarial, and compound incidents achieved 1.00 primary RCA but 0.75 exact match because the compound secondary cause was omitted.

These observability features matter methodologically: they make it possible to distinguish “the system used more reasoning” from “a configuration string claimed it did.”

## 7. Final preregistered hidden evaluation

The final protocol was committed before any hidden scenario successfully executed. Accuracy was not a CI threshold. The successful workflow started from a clean Compose environment, verified the frozen research contract, ran all ten hidden scenarios, performed post-hoc EvaluationLab scoring, queried persisted cost/latency summaries, checked ChaosLab restoration and critical logs, uploaded safe research artifacts, and tore down the environment.

Authoritative first successful execution:

- commit: `e9295448e7b96f5527863a8f00416fe0fa05d85e`;
- workflow: `34260392909`;
- artifact digest: `sha256:9e5f7aca335941b0126054434615d1d5989fc53f4ea114e082e08b0e6a96780a`.

### 7.1 Final metrics

| Metric | Result |
| --- | ---: |
| Hidden runs | 10 |
| Primary RCA accuracy | 0.80 |
| Exact match | 0.20 |
| Adversarial primary accuracy | 1.00 |
| Compound primary accuracy | 0.75 |
| Compound secondary recall | 0.00 |
| Evidence precision | 0.7833 |
| Evidence recall | 0.475 |
| Critical-evidence recall | 0.475 |
| Unsupported-claim rate | 0.00 |
| Brier score | 0.56501 |
| ECE | 0.573 |
| Total tool calls | 27 |
| Mean tool calls | 2.7 |
| Useful evidence/tool call | 0.75 |
| Diagnosis latency p50 | 153.839 ms |
| Diagnosis latency p95 | 388.212 ms |
| Failed tool calls | 0 |
| Budget-exhausted runs | 0 |
| Unsafe action attempts | 0 |

The deterministic local provider reported zero tokens and zero provider-estimated cost. Those are real measurements for that provider, not an estimate of hosted-model economics.

No hidden case contained a failed tool call, so tool-failure-recovery rate is null. The hidden cohort contains no scorable counterfactual family, so hidden counterfactual consistency is also null rather than inferred from validation data.

### 7.2 Failure analysis

The final failure counts were:

- `COMPOUND_CAUSE_OMISSION`: 8;
- `MISSED_EVIDENCE`: 8;
- `OVERCONFIDENCE`: 6;
- `TOOL_MISUSE`: 5.

All eight compound scenarios omitted the expected secondary cause. Six nevertheless found the correct primary cause with confidence from 0.96 to 0.99. Two compound cases produced an `inconclusive` diagnosis at confidence 0.0; the outer operational runs still completed successfully.

This creates the most important final gap: **0.80 primary accuracy versus 0.20 complete exact-match accuracy**. A benchmark that scored only the primary cause would substantially overstate the agent's ability to explain compound incidents.

The trajectories used only 2–4 tool calls despite much larger compound budgets, and no run exhausted its budget. Combined with the Phase 8 budget null result, this suggests that simply raising investigation ceilings is not the missing mechanism. Combined with the negative forced-evidence result, it also shows that mechanically requiring more observations is insufficient. The unresolved problem is how the agent decides whether a causal explanation is complete and how it turns partial evidence into calibrated multi-cause output.

## 8. Safety and human control

OpsSentinel separates investigation from operational action. Read-only and bounded diagnostic tools are risk classified; higher-risk actions enter an explicit approval lifecycle. The Incident Console exposes approve, reject, abandon, and verification states, and persisted runs can resume across process restarts.

The final hidden campaign recorded zero unsafe attempts, zero risk misclassification, and zero unnecessary approvals. This does not prove universal safety, but it shows the safety boundary remained intact under the frozen final campaign.

## 9. External validation decision

Public 2026 benchmarks including AgenticOpsEval/RCA100, RootCauseBench, and ITBench-AA are related but not plug-compatible with OpsSentinel v1.0. They use different agent surfaces and target labels: offline multimodal localization/identification/causal-chain scoring, exact culprit-commit attribution through a Terminal-Bench shell, or a separate Kubernetes benchmark harness.

Phase 10 therefore does not publish a pseudo-comparable external score. `docs/phase-10-external-validation.md` records the compatibility assessment and requirements for a future preregistered adapter study.

## 10. What the experiments support

The combined evidence supports several bounded conclusions for this implementation and benchmark.

1. **More available budget is not the same as more investigation.** The agent often stopped long before its limit.
2. **More forced investigation is not automatically better.** Full compound evidence plans increased work and could reduce primary RCA.
3. **Additional structure can be behaviorally real yet diagnostically null.** Explicit planning and temporal metadata changed mechanisms without improving sampled outcomes.
4. **Verification has a measurable cost.** In the sampled baseline it did not improve diagnosis or calibration.
5. **Primary RCA can hide incomplete causal understanding.** The final 0.80 primary / 0.20 exact-match gap is the strongest evidence for reporting compound completeness separately.
6. **Confidence needs a notion of completeness.** Six incomplete compound diagnoses were reported near 1.0 confidence.
7. **The strongest persistent weakness is interpretation, not raw tool access.** The agent can often observe and identify an acute primary fault but fails to retain genuine secondary causes.

## 11. Limitations and threats to validity

- The provider/model baseline is deterministic and local. Findings are not population estimates over frontier hosted LLMs.
- Phase 8 and Phase 10 cohorts are controlled engineering samples, not claims about all production incidents.
- The final hidden split is intentionally weighted toward adversarial and compound structures.
- Provider token/cost values are zero in the local baseline; tool calls, retrieval depth, and latency are more informative resource proxies here.
- The validation no-fault control remained weak in several Phase 8 experiments and was not hidden or relabeled.
- Hidden counterfactual consistency is unavailable because the frozen hidden split contains no counterfactual family.
- No numeric external-benchmark result is reported because current public candidates require materially different agent/harness interfaces.
- Human approval quality itself was not experimentally compared; the project validates the approval boundary and UI behavior, not a causal claim that humans improve outcomes.

## 12. Reproducibility

Research definitions are versioned and protected by the Phase 10 freeze verifier. The published safe hidden summary is `results/phase10/heldout-summary.json`; detailed interpretation is in `docs/phase-10-heldout-results.md`.

Useful commands:

```bash
# ordinary non-container CI-equivalent checks
make setup
make ci

# verify that Benchmark v1.0 and frozen evaluator definitions have not changed
make phase10-freeze

# reproduce the hidden workflow from a clean Compose stack
# (a regression/reproducibility run; do not replace the first successful published result)
make phase10-heldout
```

Phase-specific GitHub Actions remain the authoritative clean-run evidence for guarded merge and post-merge validation.

## 13. Conclusion

OpsSentinel's final result is intentionally mixed. The platform can execute bounded autonomous investigations, persist/recover state, preserve evaluator isolation, expose traces/cost/latency, enforce human approval boundaries, and solve the primary cause of most final hidden incidents. Yet its strongest failure mode is scientifically important: a plausible primary diagnosis can arrive quickly and with very high confidence while the complete causal explanation remains wrong.

That result argues against using a single RCA-accuracy number to evaluate incident-response agents. Complete multi-cause correctness, evidence completeness, calibration, effort, failure behavior, and safety need to be measured separately. In this baseline, giving the agent more reasoning machinery did not reliably solve the problem. The next research direction is not simply “let it think longer”; it is to design and test mechanisms that recognize unresolved causal structure and calibrate confidence to explanation completeness.
