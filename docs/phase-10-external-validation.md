# Phase 10 External Validation Decision

## Decision

OpsSentinel Benchmark v1.0 will **not publish a numeric external-benchmark score** in the Phase 10 release.

This is a methodological decision, not a claim that no relevant public SRE benchmark exists. Several 2026 public benchmarks are highly relevant, but none can be executed by the existing OpsSentinel runtime without introducing a substantial task/harness adapter that would change what is being measured.

The Phase 10 specification makes external validation optional and requires it to be honest. For this release, preserving task validity is preferable to manufacturing an apparently comparable score from incompatible labels, tool surfaces, or execution environments.

## Candidates reviewed

### AgenticOpsEval / RCA100

AgenticOpsEval is a 2026 multi-dataset benchmark for LLM-agent microservice diagnosis. Its public release reports 503 expert-labeled cases across AIOps2025 and RCA100. RCA100 contains 103 chaos-drill incidents from a Kubernetes/OpenTelemetry demo store and about 3.4 GB of metrics, logs, traces, events, alerts, and topology. The benchmark evaluates localization, fault identification, and evidence/reasoning quality.

Sources:

- paper: <https://arxiv.org/abs/2606.29193>
- repository: <https://www.aiops.cn/gitlab/aiops-live-benchmark/agenticopseval>

Why it is not a drop-in external test for this release:

1. RCA100 is an offline multimodal artifact benchmark; OpsSentinel is built around a live bounded incident API and MCP investigation tools over a running simulator.
2. The external target labels are localization/identification/causal-chain oriented rather than OpsSentinel's frozen primary/secondary cause, evidence, calibration, safety, and operational-run contract.
3. A faithful adapter would need to expose parquet/log/trace/topology evidence as a new tool environment and define an explicit mapping from external labels to OpsSentinel outputs.
4. That adapter would be a material new evaluation architecture in Phase 10, precisely when the project is supposed to validate and release the system already built rather than invent a new benchmark-specific agent surface.
5. RCA100 is CC BY-NC-SA 4.0 and AIOps2025 is CC BY-NC 4.0; reuse would also require explicit attribution/license handling in any redistributed derivative artifacts.

AgenticOpsEval is the best candidate for a future external-validation branch because its multimodal microservice RCA setting is close to the OpsSentinel research question. That work should be preregistered separately and should retain the external benchmark's own metrics rather than converting them into an OpsSentinel v1.0 score.

### RootCauseBench

RootCauseBench is an open Apache-2.0 benchmark that gives a model frozen telemetry plus change context and asks for the exact Git commit responsible for a production regression. It runs as Terminal-Bench tasks through the Harbor harness, with a shell-oriented agent environment and exact culprit-SHA grading.

Source: <https://github.com/edgedelta/root-cause-bench>

Why it is not comparable enough for a Phase 10 score:

1. its primary task is culprit-commit attribution, while OpsSentinel v1.0 diagnoses operational fault classes and compound primary/secondary causes;
2. its agent surface is a shell over static files, not the OpsSentinel MCP investigation boundary;
3. its primary metric is exact commit identification, so any mapping to OpsSentinel RCA accuracy would be arbitrary;
4. using OpsSentinel unchanged would deny it the benchmark's intended shell/data interface, while adapting it substantially would evaluate a different system.

### ITBench-AA SRE

ITBench-AA evaluates agentic Kubernetes incident response on live systems and is conceptually close to OpsSentinel. Public descriptions emphasize root-cause-entity diagnosis through logs and dependency inspection.

Source: <https://artificialanalysis.ai/articles/itbench-aa-launch>

It is not used for the Phase 10 release because the benchmark uses its own agent/harness protocol and scoring contract. A defensible comparison would require a supported adapter and explicit agreement on task and metric equivalence rather than treating leaderboard scores as interchangeable with OpsSentinel Benchmark v1.0.

## External-validation rule for future work

A future OpsSentinel external study should satisfy all of the following before execution:

- preregister the external dataset/version and exact subset;
- preserve the external benchmark's original ground truth and metrics;
- define an adapter that exposes only agent-visible evidence and never evaluator truth;
- document every mapping between external entities/fault types and OpsSentinel output fields;
- freeze the adapter and scoring contract before examining final external results;
- report external metrics separately from OpsSentinel Benchmark metrics;
- retain negative/null outcomes;
- comply with dataset licenses and attribution requirements.

Until that exists, the Phase 10 release reports the frozen internal held-out result and describes external benchmarks as related validation opportunities, not as pseudo-comparable scores.
