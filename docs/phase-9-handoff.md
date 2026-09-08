# Phase 9 Handoff — Cost/Accuracy Optimization, Observability, and Human-AI System

## Status

**PRE-MERGE ACCEPTED.** Phase 9 implementation and the pre-merge cumulative acceptance matrix have passed. Phase 9 is not fully closed until PR #11 is merged with its expected head SHA and the resulting `main` merge commit passes post-merge cumulative CI.

Phase 9 started from the fully closed Phase 8 `main` head `fae661fc1634aad6a3855a1dec8dcddb16a890dd`.

Current branch: `phase-9-cost-observability-ui`.

Implementation acceptance head before this documentation synchronization: `70db8a9021325ba7698189cdd0aa9c1e59dc1dcf`.

The documentation synchronization commit that contains this file must itself pass the same exact-head checks before PR #11 is marked ready and merged.

## Objective

Make cost, latency, accuracy, and investigation effort measurable; expose autonomous incident investigations to humans through operational and research views; and add production-style tracing/metrics without weakening the evidence-grounding, safety, BenchmarkLab, EvaluationLab, or ResearchLab guarantees established in Phases 1–8.

## Accepted Phase 9 capabilities

### 9.1 Durable cost and run accounting

- typed per-operation model execution records for planning, hypothesis updates, evidence sufficiency, diagnosis, and recommendation;
- durable input/output token counts, provider-estimated cost, model/tool latency, provider/model identity, success/failure status, and timestamps;
- aggregate run accounting linked to existing tool calls, evidence, checkpoints, and agent runs;
- `GET /observability/runs/{run_id}/cost`;
- explicit missing measurements instead of converting missing data to zero;
- deterministic/local providers are allowed to report real zero tokens and `$0` cost;
- metering failures are logged without replacing the provider output or exception.

### 9.2 Cost/accuracy Pareto analysis

The accepted campaign contains 80 real trials over ten validation scenarios and eight preregistered configurations.

The sampled dimensions are tool budget, planning strategy, retrieval depth, and verification strategy. The model dimension is explicitly `unsampled_fixed_local_placeholder`; Phase 9 therefore makes no cross-model Pareto claim.

Because the local provider reports legitimate zero tokens and zero monetary cost, the report uses the declared resource proxy:

`mean_tool_calls + mean_total_tokens / 1000 + mean_retrieved_evidence / 10`

Measured results:

- frontier configurations: `p9-c01`, `p9-c04`, `p9-c06`, `p9-c07`;
- each frontier configuration measured 0.80 mean diagnostic accuracy and 0.80 exact-match rate with 2.4 mean tool calls and 2.4 mean retrieved evidence;
- verification-enabled configurations used 3.4 mean tool calls/retrieved evidence and did not improve accuracy in this cohort; two verification arms measured 0.70 accuracy;
- every sampled configuration retained the validation negative-control false positive rather than hiding or relabeling it;
- Pareto report artifact digest on the accepted head: `sha256:bb50ce9d12c310785519b4ae27787d3fa1c5719c4dfaa74db27be22b60784f20`.

This is multi-factor optimization evidence, not a causal attribution to any single factor.

### 9.3 Latency analysis

Live approval-path validation measured and persisted:

- time to first investigation step: p50 22.234 ms, p95 32.003 ms;
- time to diagnosis: p50 497.728 ms, p95 507.223 ms;
- time to verified resolution: one measured approved run at 1320.836 ms;
- the rejected run correctly retained `time_to_verified_resolution = null`;
- restart persistence was verified.

The local deterministic provider again reported zero tokens and `$0` cost truthfully.

Accepted latency artifact digest: `sha256:b7793a007097c553b5d5d7e02e26ef00c06066d74a29c6883ad14ec7ac61218c`.

### 9.4 Distributed OpenTelemetry

Opt-in browser tracing propagates W3C trace context through the real frontend → FastAPI → agent graph → MCP → ChaosLab path.

The trace implementation includes agent/node/tool spans, backend and ChaosLab instrumentation, service isolation, and request-target redaction. Verification fails closed on hidden-state/tool-argument leakage, and raw collector output is not retained as a CI artifact.

On exact head `70db8a9021325ba7698189cdd0aa9c1e59dc1dcf`, `Phase 9 OpenTelemetry` run `34254185105` passed both integrity and live distributed-trace jobs, including clean stack startup, privacy controls, clean operational state, critical-log checks, and teardown.

### 9.5 Prometheus and Grafana

Phase 9 adds Prometheus-compatible backend/agent accounting and operational metrics plus Grafana dashboards that keep operational and research views distinct. The deterministic provider's zero token/cost measurements remain visible as zero rather than being replaced by synthetic non-zero values.

On the accepted head, `Phase 9 Prometheus Grafana` run `34254185294` passed.

### 9.6 Self-hosted Langfuse

A self-hosted Langfuse v4 stack is provided through `docker-compose.langfuse.yml` with dedicated PostgreSQL, Redis, ClickHouse, MinIO, worker, and web services.

The existing OpenTelemetry pipeline exports safe Langfuse observation semantics for agent, chain, tool, and generation spans. Generation observations include model identity, latency, truthful usage/cost details, and safe experiment/run metadata without raw evidence, benchmark truth, or injected fault state.

The live proof runs a real BenchmarkLab scenario through the agent, evaluates it only after agent completion, attaches the real EvaluationLab score post-hoc, then restarts Langfuse web/worker and verifies trace/score readback.

On the accepted head, `Phase 9 Langfuse` run `34254185273` passed. Safe artifact digest: `sha256:d680f7a356bca4b6ae66cadca18dc5519085e12063edc359afbeaa2064f2f90d`.

### Human-AI Incident Console

The React Incident Console now provides:

- incident overview and bounded investigation launch;
- ordered investigation timeline;
- separate evidence and hypothesis panels;
- diagnosis and compound-RCA display;
- explicit approval/rejection/abandon controls for operational actions;
- post-action verification state;
- loading, error, agent-failure, approval, rejection, completed, and compound states;
- cost/latency measurement panels that distinguish missing measurements from measured zero values.

The UI never displays benchmark ground truth, simulator-only causal labels, or injected fault state.

`Phase 9 Incident Console` run `34254185038` passed on the accepted head.

### Experiment Dashboard and persisted evaluator cross-check

`GET /observability/experiments` projects persisted EvaluationLab/experiment data for the research dashboard. The dashboard preserves configuration, tool budget, retrieval settings, scenario counts, linked agent-run counts, evaluator metrics, failure categories, and null-vs-zero semantics.

The live acceptance proof starts from a fresh PostgreSQL database, applies migrations from zero, persists canonical `SqlEvaluationStore` output, cross-checks raw score rows against EvaluationLab, starts the real FastAPI backend, reads the API projection, restarts the backend, reads it again, and performs migration rollback/re-upgrade.

`Phase 9 Experiment Dashboard` run `34254185080` passed on the accepted head.

### Actual-frontend representative incidents

A clean-state Playwright gate executes preregistered BenchmarkLab representatives through the real human frontend. The browser is the only agent-launch path. The harness activates scenario faults/stimuli externally, but the browser POST contains only public incident fields and carries no scenario ID or hidden ground truth.

Representatives:

- easy: `ops-v1-001`;
- hard: `ops-v1-033`;
- adversarial: `ops-v1-035`;
- compound: `ops-v1-043`.

All four runs completed, rendered terminal/timeline/evidence/hypothesis states, survived backend restart readback, restored ChaosLab faults, and recorded zero unsafe action attempts.

Measured evaluation:

- aggregate primary root-cause accuracy: 1.00;
- exact-match rate: 0.75;
- easy/hard/adversarial exact match: true;
- compound primary cause: correct, but secondary-cause exact match: false;
- retained compound failure categories: `MISSED_EVIDENCE`, `TOOL_MISUSE`, `COMPOUND_CAUSE_OMISSION`, `OVERCONFIDENCE`.

This compound miss is a research result, not a CI defect, and was not tuned away.

Accepted representative artifact digest: `sha256:649cf7df2bac827e0da60324dac9c41fab648eadcda2cf4789b99b86dcd0c1f1`.

## Cumulative pre-merge acceptance evidence

On exact head `70db8a9021325ba7698189cdd0aa9c1e59dc1dcf`, every returned required workflow completed successfully:

- cumulative `CI` run `34254185086`;
- `Phase 6 BenchmarkLab` run `34254185220`;
- `Phase 7 EvaluationLab` run `34254185071`;
- `Phase 8 ResearchLab` run `34254185193`;
- `Phase 8 H3 Temporal Reasoning` run `34254185047`;
- `Phase 8 Tool Order` run `34254185061`;
- `Phase 8 Passive vs Verification` run `34254185134`;
- `Phase 8 Compound Handling` run `34254185312`;
- `Phase 9 Pareto` run `34254185136`;
- `Phase 9 Latency` run `34254185077`;
- `Phase 9 OpenTelemetry` run `34254185105`;
- `Phase 9 Prometheus Grafana` run `34254185294`;
- `Phase 9 Langfuse` run `34254185273`;
- `Phase 9 Incident Console` run `34254185038`;
- `Phase 9 Experiment Dashboard` run `34254185080`;
- `Phase 9 Representative Frontend` run `34254185155`.

The base `CI` workflow is the cumulative clean-state/restart gate: Ruff/mypy/unit/integration tests, migrations and rollback/re-upgrade, clean Docker Compose startup, Phase 2–7 live smokes, persistence checks, load generation, log inspection, fault cleanup, restart cleanup, and teardown. The Phase 8/9 dedicated workflows extend that exact-head gate with the controlled research and observability/UI surfaces added later.

## Research integrity and known limitations

- The current provider/model baseline is local and deterministic. Reported zero token usage and `$0` provider cost are legitimate measurements.
- The Phase 9 Pareto model dimension was not sampled; no cross-model optimization conclusion is supported.
- Validation negative controls still expose a no-fault false positive in the sampled Pareto campaign.
- The representative compound frontend run still omits a secondary cause even though the primary cause is correct.
- Phase 8 null/negative findings remain unchanged and first-class.
- No optional human-approval quality study was performed. Phase 9 does not fabricate one or treat its omission as evidence about human decision quality.

## Remaining closure steps

Only repository closure remains:

1. this README/handoff synchronization commit must pass the exact-head cumulative CI + Phase 8/9 matrix;
2. PR #11 must be marked ready only after those checks are green;
3. merge must be guarded with the expected PR head SHA;
4. the resulting `main` merge commit must pass post-merge cumulative CI before Phase 9 is declared fully closed and Phase 10 begins.

## Guarantee after post-merge closure

After the post-merge `main` proof passes, later phases may rely on durable cost/latency accounting, sampled Pareto analysis, distributed tracing, operational/research metrics, self-hosted Langfuse, the human Incident Console, persisted experiment dashboards, and clean-state frontend representative validation without weakening the safety or evaluator-isolation boundaries established in earlier phases.
