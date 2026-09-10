# OpsSentinel

[![CI](https://github.com/sadmanHT/OpsSentinel/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sadmanHT/OpsSentinel/actions/workflows/ci.yml)

**Autonomous AI incident response with deterministic fault simulation, evidence-grounded diagnosis, human approval controls, observability, and a frozen evaluation benchmark.**

OpsSentinel is a production-style AI engineering project that investigates real incident-response behavior instead of presenting a scripted chatbot demo. It runs against a deterministic microservice environment, lets an autonomous agent investigate incidents through constrained tools, persists its reasoning state and evidence, exposes the workflow through a React operator console, and evaluates the resulting diagnosis with a separate benchmark and scoring system.

The core question is simple:

> **Can an AI agent explain an incident completely, safely, and efficiently—not just guess the most obvious root cause?**

## What OpsSentinel does

- **Simulates production incidents** with a deterministic microservice environment and controlled fault injection.
- **Investigates autonomously** with a LangGraph-based agent using constrained MCP tools for logs, metrics, health, deployment context, and verification.
- **Builds evidence-backed diagnoses** with explicit hypotheses, evidence provenance, confidence, primary causes, and secondary causes.
- **Keeps humans in control** through approval, rejection, abandon, and post-action verification flows for operational actions.
- **Persists investigations** in PostgreSQL so runs, evidence, approvals, evaluations, and experiment results survive restarts.
- **Measures the agent independently** with a frozen 50-scenario benchmark and EvaluationLab metrics for RCA quality, evidence use, calibration, efficiency, and safety.
- **Provides production observability** with OpenTelemetry, Prometheus, Grafana, Langfuse, and durable tool/token/cost/latency accounting.
- **Tests the full system** with browser E2E checks, clean Docker Compose startup, restart/persistence validation, migrations, and cumulative CI.

## Product

<table>
<tr>
<td width="50%" valign="top">
<strong>Incident Console</strong><br><br>
Operator-facing investigation workspace with timeline, evidence/hypothesis separation, diagnosis confidence, secondary causes, human approval boundaries, verification, and run cost/latency.
<br><br>
<img src="docs/assets/incident-console-light.webp" alt="OpsSentinel Incident Console" width="100%" />
</td>
<td width="50%" valign="top">
<strong>Experiment Dashboard</strong><br><br>
Persisted evaluation and experiment view for comparing RCA performance, evidence quality, tool use, safety, configuration, retrieval depth, and failure categories.
<br><br>
<img src="docs/assets/experiment-dashboard-light.webp" alt="OpsSentinel Experiment Dashboard" width="100%" />
</td>
</tr>
</table>

### Observability

OpsSentinel exports system and agent telemetry through OpenTelemetry, Prometheus/Grafana, and Langfuse. The dashboards track agent runs, tool calls, latency, durable state, model execution, and provider-reported usage without fabricating missing data or non-zero cost.

<p align="center">
  <img src="docs/assets/grafana-observability.webp" alt="OpsSentinel Grafana observability dashboard" width="700" />
</p>

## Demo

The product surfaces above form the reviewer-facing walkthrough:

1. Start an investigation from the **Incident Console** and watch the agent move from triage to evidence collection, hypothesis updates, diagnosis, and—when required—human approval and verification.
2. Inspect the persisted evidence and tool history to see what the agent actually observed rather than relying on hidden chain-of-thought or simulator ground truth.
3. Open the **Experiment Dashboard** and **Grafana** view to compare evaluation outcomes, failure categories, tool effort, latency, and provider-reported usage.

For an interactive local demo, start the stack with `make clean-start`, then open `http://localhost:5173/`. ChaosLab remains a test-harness boundary and is never exposed to the agent as a source of hidden fault truth.

## Architecture

```mermaid
flowchart LR
    U[Operator] --> FE[React Incident Console\nExperiment Dashboard]
    FE --> API[FastAPI Backend]
    API --> AG[LangGraph Agent Runtime]
    AG --> MCP[Constrained MCP Tools]
    MCP --> SVC[Service Logs / Metrics / Health]

    CHAOS[ChaosLab\nDeterministic Fault Injection] --> SVC

    API --> DB[(PostgreSQL / pgvector)]
    API --> REDIS[(Redis)]

    API --> OTEL[OpenTelemetry]
    OTEL --> PROM[Prometheus / Grafana]
    API --> LF[Langfuse]

    BENCH[BenchmarkLab\n50 Scenarios] --> EVAL[EvaluationLab]
    API --> EVAL
    EVAL --> DB

    GT[(Hidden Ground Truth)] -. evaluator only .-> EVAL
```

The agent never receives benchmark ground truth or the fault-controller state. Those remain outside the reasoning boundary so the evaluation measures diagnosis rather than hidden-label leakage.

## Main components

| Component | Purpose |
| --- | --- |
| **Agent Runtime** | LangGraph investigation loop, bounded tool use, persisted state, hypotheses, diagnosis, and verification |
| **MCP Tools** | Constrained operational interface for logs, metrics, health, deployment context, and approved actions |
| **ChaosLab** | Deterministic production-like service simulator and controlled fault injection |
| **BenchmarkLab** | Versioned 50-scenario benchmark with dev, validation, and hidden-test splits |
| **EvaluationLab** | RCA, evidence, efficiency, calibration, safety, counterfactual, and failure-taxonomy scoring |
| **ResearchLab** | Reproducible controlled experiments over investigation strategies and configurations |
| **Incident Console** | Human-facing React interface for investigation state and approval boundaries |
| **Experiment Dashboard** | Persisted experiment/evaluation comparison UI |
| **Observability Stack** | OpenTelemetry, Prometheus, Grafana, Langfuse, and cost/latency accounting |

## Evaluation results

The authoritative preregistered hidden-test campaign ran **10 untouched scenarios** from the frozen OpsSentinel Benchmark v1.0.

> **Evaluation provider:** the published Benchmark v1.0 numbers use OpsSentinel's deterministic evidence-driven reasoning provider for reproducibility and ground-truth isolation. The runtime also supports Ollama/local LLM execution; those LLM runs are **not** represented by the published benchmark numbers. This is also why the authoritative held-out run reports `0` provider tokens and `$0` provider-estimated cost.

| Metric | Result |
| --- | ---: |
| Primary RCA accuracy | **0.80** |
| Complete exact-match accuracy | **0.20** |
| Adversarial primary accuracy | **1.00** |
| Compound primary accuracy | **0.75** |
| Compound secondary-cause recall | **0.00** |
| Evidence precision | **0.7833** |
| Critical-evidence recall | **0.475** |
| Brier score | **0.56501** |
| Expected calibration error | **0.573** |
| Mean tool calls | **2.7** |
| Diagnosis latency p50 / p95 | **153.839 / 388.212 ms** |
| Failed tool calls | **0** |
| Unsafe action attempts | **0** |

### The important result

**80% primary RCA accuracy hid only 20% complete diagnosis accuracy.**

The agent was often good at identifying the acute primary failure, but compound incidents exposed a deeper weakness: it frequently stopped after finding one convincing cause and failed to explain a genuine secondary cause. Several incomplete compound diagnoses were still returned with very high confidence.

That makes OpsSentinel useful as more than an incident-response demo: the project measures **completeness, evidence coverage, calibration, tool efficiency, and safety**, not just whether one root-cause label matched.

## Experiments and trade-offs

ResearchLab tested whether adding more reasoning structure or investigation effort actually improved diagnosis. The important outcomes were mixed rather than optimized away:

| Comparison | Measured outcome |
| --- | --- |
| Reactive ReAct vs explicit planning | No sampled diagnostic improvement; compound secondary-cause omission remained |
| Tool budgets 5 / 10 / 15 / 20 | All produced 0.80 RCA / 0.80 exact match with ~2.4 mean calls; the agent usually stopped before the smallest ceiling |
| Deployment-first tool ordering | Increased mean calls from 2.8 to 3.6 without improving diagnosis |
| Passive evidence vs active verification | Verification increased mean calls from 2.4 to 3.4 and roughly doubled sampled latency without improving diagnosis or calibration |
| Compound unresolved-evidence strategy | Increased mean calls from 4.75 to 10.0, slightly increased evidence recall, reduced primary RCA from 0.75 to 0.50, and recovered no secondary causes |

### Cost / accuracy frontier

A sampled 80-trial Pareto campaign varied tool budget, planning strategy, retrieval depth, and verification strategy. The strongest frontier configurations reached **0.80 mean RCA/exact match with 2.4 mean tool calls**. Verification-enabled configurations used more calls without improving the best sampled accuracy. The model/provider dimension was intentionally fixed to the deterministic local provider, so OpsSentinel does **not** claim a cross-model cost frontier from these results.

The overall conclusion is not “more reasoning is better.” The persistent bottleneck is deciding whether the current causal explanation is complete and calibrating confidence to that completeness.

## Safety and human control

OpsSentinel separates diagnosis from operational authority.

- Low-risk read-only investigation tools can run automatically.
- Higher-risk operational actions require explicit human approval.
- Approval requests carry rationale, evidence, expected benefit, risk, and rollback context.
- Rejected or abandoned actions remain visible in the persisted investigation history.
- Approved actions are followed by deterministic verification.
- Unsafe attempts are measured independently by EvaluationLab.

The final hidden-test campaign recorded **0 unsafe action attempts**.

## Observability and persistence

Every investigation is designed to be inspectable after the fact. OpsSentinel records agent runs, tool calls, evidence, hypotheses, approvals, model execution, latency, token/cost measurements, and evaluation results. Missing measurements remain missing; legitimate zero values remain zero.

The system also validates restart behavior: persisted investigations and evaluation data are read back after backend/database restarts rather than relying on in-memory state.

## Technology stack

- **AI / agents:** Python, LangGraph, structured tool use, MCP, provider abstraction
- **Backend / data:** FastAPI, PostgreSQL, pgvector, Redis, SQLAlchemy, Alembic
- **Frontend:** React, TypeScript, Playwright
- **Observability:** OpenTelemetry, Prometheus, Grafana, Langfuse
- **Infrastructure:** Docker, Docker Compose, GitHub Actions
- **Evaluation:** BenchmarkLab, EvaluationLab, calibration metrics, evidence scoring, failure taxonomy

## Run locally

> [!WARNING]
> The included Docker Compose configuration is a **local research/development stack**, not an Internet-facing production deployment. Services are bound to loopback, the simulator deliberately exposes test controls, and development credentials are convenient defaults. Do not expose this stack publicly without adding deployment-specific authentication, secret management, TLS/network policy, and authorization around operator actions.

Requirements: Python 3.11+, Docker Compose, Node/npm, and the repository development dependencies.

```bash
cp .env.example .env
make setup
make ci
```

Start the full local environment:

```bash
docker compose down -v
make clean-start
```

Useful endpoints:

- Incident Console: `http://localhost:5173/`
- Backend health: `http://localhost:8000/health`
- MCP tools: `http://localhost:8000/mcp/tools`
- Experiment API: `http://localhost:8000/observability/experiments`
- Run cost/latency: `http://localhost:8000/observability/runs/{run_id}/cost`
- ChaosLab controller: `http://localhost:8100/health` — test harness only, never agent-visible

## Reproducibility

- `frontend/package-lock.json` is committed and CI/container builds use `npm ci`.
- `backend/requirements.lock` pins the backend runtime dependency graph.
- `backend/requirements-dev.lock` pins the backend development/test dependency graph.
- Core PostgreSQL/pgvector and Redis Compose images are digest-pinned.
- The benchmark release separately freezes benchmark and evaluator source blobs before held-out execution.

For the research contract specifically:

```bash
make phase10-freeze
make phase10-heldout
```

`phase10-heldout` is a reproducibility/regression run; it does not replace the first successful preregistered hidden-test result recorded in the published research artifacts.

## Limitations

- The published baseline uses a **deterministic local reasoning provider**. Its results should not be generalized to frontier hosted LLMs.
- The final hidden cohort contains only 10 scenarios and is deliberately weighted toward adversarial and compound structures; it is not a production incident-frequency estimate.
- Provider-reported token usage and monetary cost are zero for the deterministic baseline, so tool calls, retrieval depth, and latency are the more informative resource measures for that campaign.
- Compound diagnosis remains the main weakness: secondary-cause recall was 0.00 in the final hidden evaluation despite strong primary-cause performance.
- Hidden counterfactual consistency is unavailable because the frozen hidden cohort contains no scorable counterfactual family.
- Human approval flow is validated as a safety/control boundary, but the project does not claim that a human-participant study proved better operational decisions.
- Related public SRE/agent benchmarks use materially different task and tool surfaces; OpsSentinel therefore does not publish an artificial directly-comparable external score.
- The included Compose stack is designed for local research/development, not direct Internet-facing deployment.

## Repository layout

```text
backend/          FastAPI APIs, agent runtime, persistence, observability
frontend/         React Incident Console and Experiment Dashboard
chaoslab/         deterministic service simulator and fault injection
benchmarklab/     versioned benchmark scenarios and protected ground truth
evaluationlab/    evaluation metrics, calibration, safety, failure taxonomy
researchlab/      controlled experiment orchestration
observability/    Prometheus / Grafana configuration
results/          published evaluation outputs
scripts/          reproducibility and validation helpers
```

## Research integrity

- Hidden ground truth is evaluator-only.
- Benchmark and scoring definitions are frozen before held-out evaluation.
- Performance metrics are research data, not CI pass thresholds.
- Null and negative findings are retained rather than tuned away.
- Missing values are not silently converted to zero.
- The first successful preregistered hidden-test result remains the authoritative research snapshot.

## Documentation

- `docs/architecture.md` — final system architecture and trust boundaries
- `docs/research-report.md` — technical and research report
- `docs/evaluationlab.md` — evaluator and metric contract
- `docs/chaoslab.md` — simulator and fault model
- `docs/mcp-safety.md` — tool safety and approval boundary
- `docs/phase-10-heldout-results.md` — detailed hidden-test metrics and failure analysis

## License

Licensed under the [MIT License](LICENSE).

---

OpsSentinel is built to demonstrate the part of AI engineering that is easy to hide in a demo: **what the agent actually observed, why it acted, whether its diagnosis was complete, how confident it was, how much work it used, and whether the system remained safe and reproducible.**
