import { useEffect, useMemo, useState, type FormEvent } from 'react'

import {
  decideApproval,
  getInvestigation,
  getRunCostSummary,
  resumeInvestigation,
  startInvestigation,
  type AgentRunStatus,
  type AgentRunView,
  type ApprovalDecision,
  type Incident,
  type RunCostSummary,
  type StartInvestigationPayload,
} from './api'
import {
  browserTracingEnabled,
  startInvestigation as startTracedInvestigation,
} from './observability'
import './styles.css'

const traceProofEnabled = browserTracingEnabled()

const severityOptions: Incident['severity'][] = ['P0', 'P1', 'P2', 'P3', 'P4']
const pollingStatuses = new Set<AgentRunStatus>(['created', 'running'])

type TimelineItem = {
  id: string
  timestamp: string
  kind: 'incident' | 'tool' | 'evidence' | 'failure' | 'approval' | 'report'
  title: string
  detail: string
  tone?: 'positive' | 'warning' | 'critical'
}

function traceProofPayload() {
  return {
    incident: {
      title: 'Phase 9.4 browser trace proof',
      description:
        'Checkout latency and errors increased during a public incident. Investigate using legal observable evidence only.',
      severity: 'P2',
      service: 'checkout',
      start_time: new Date().toISOString(),
      status: 'open',
    },
    pause_after: 'store_evidence',
    operational_mode: false,
  }
}

function TraceProof() {
  const [proofStatus, setProofStatus] = useState('idle')
  const [traceId, setTraceId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  async function runTraceProof() {
    setProofStatus('running')
    setErrorMessage(null)
    try {
      const result = await startTracedInvestigation(traceProofPayload())
      setTraceId(result.traceId)
      setRunId(result.runId)
      setProofStatus(result.status ?? 'completed')
    } catch (error) {
      const failure = error instanceof Error ? error.message : String(error)
      setErrorMessage(failure)
      setProofStatus('error')
    }
  }

  return (
    <main className="trace-proof-shell">
      <p className="eyebrow">OpsSentinel</p>
      <h1>Autonomous incident-response research platform</h1>
      <section aria-label="Phase 9.4 trace proof" className="trace-proof-card">
        <h2>Phase 9.4 distributed trace proof</h2>
        <p>
          Starts one bounded checkout investigation and pauses after the first stored evidence so
          browser, API, agent, MCP, and simulator spans can be verified under one trace ID.
        </p>
        <button
          className="primary-button"
          data-testid="trace-proof-run"
          disabled={proofStatus === 'running'}
          onClick={() => void runTraceProof()}
          type="button"
        >
          {proofStatus === 'running' ? 'Running trace proof…' : 'Run trace proof'}
        </button>
        <p data-testid="trace-proof-status">Status: {proofStatus}</p>
        {traceId ? <p data-testid="trace-id">Trace ID: {traceId}</p> : null}
        {runId ? <p data-testid="run-id">Run ID: {runId}</p> : null}
        {errorMessage ? <p data-testid="trace-error">Error: {errorMessage}</p> : null}
      </section>
    </main>
  )
}

function formatDate(value: string | null | undefined): string {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`
}

function formatMilliseconds(value: number | null): string {
  if (value === null) return 'Not measured'
  if (value === 0) return '0 ms'
  if (value < 1000) return `${Math.round(value)} ms`
  return `${(value / 1000).toFixed(2)} s`
}

function formatLatency(value: number | null): string {
  return value === null ? 'Not measured' : `${Math.round(value)} ms`
}

function formatCost(value: number): string {
  if (value === 0) return '$0.0000'
  if (value < 0.01) return `$${value.toFixed(6)}`
  return `$${value.toFixed(4)}`
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function statusLabel(status: string): string {
  return status.replaceAll('_', ' ')
}

function buildTimeline(run: AgentRunView): TimelineItem[] {
  const items: TimelineItem[] = [
    {
      id: `incident-${run.incident.id}`,
      timestamp: run.incident.start_time,
      kind: 'incident',
      title: `${run.incident.severity} incident opened`,
      detail: `${run.incident.service} · ${run.incident.title}`,
    },
  ]

  run.tool_history.forEach((call) => {
    items.push({
      id: `tool-${call.id}`,
      timestamp: call.started_at,
      kind: 'tool',
      title: call.tool_name,
      detail: `${statusLabel(call.status)} · ${call.risk_level}`,
      tone: call.status === 'failed' || call.status === 'blocked' ? 'warning' : undefined,
    })
  })

  run.evidence.forEach((evidence) => {
    items.push({
      id: `evidence-${evidence.id}`,
      timestamp: evidence.timestamp,
      kind: 'evidence',
      title: `${evidence.evidence_type} evidence stored`,
      detail: evidence.observation,
      tone: 'positive',
    })
  })

  run.failures.forEach((failure, index) => {
    items.push({
      id: `failure-${failure.recorded_at}-${index}`,
      timestamp: failure.recorded_at,
      kind: 'failure',
      title: `${failure.tool} · ${failure.code}`,
      detail: failure.message,
      tone: 'critical',
    })
  })

  if (run.approval) {
    items.push({
      id: `approval-created-${run.approval.id}`,
      timestamp: run.approval.created_at,
      kind: 'approval',
      title: 'Human approval requested',
      detail: `${run.approval.action.risk_level} · ${run.approval.action.description}`,
      tone: 'warning',
    })
    if (run.approval.decided_at) {
      items.push({
        id: `approval-decided-${run.approval.id}`,
        timestamp: run.approval.decided_at,
        kind: 'approval',
        title: `Approval ${run.approval.decision}`,
        detail: run.approval.decided_by
          ? `Decision by ${run.approval.decided_by}`
          : 'Decision actor not recorded',
        tone: run.approval.decision === 'approved' ? 'positive' : 'warning',
      })
    }
  }

  if (run.report) {
    items.push({
      id: `report-${run.report.run_id}`,
      timestamp: run.report.generated_at,
      kind: 'report',
      title: 'Grounded report generated',
      detail: `${run.report.root_cause_code} · ${formatPercent(run.report.diagnosis.confidence)} confidence`,
      tone: 'positive',
    })
  }

  return items.sort((left, right) => {
    const leftTime = new Date(left.timestamp).getTime()
    const rightTime = new Date(right.timestamp).getTime()
    return leftTime - rightTime
  })
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      {hint ? <small>{hint}</small> : null}
    </div>
  )
}

function EmptyState({ children }: { children: string }) {
  return <p className="empty-state">{children}</p>
}

function IncidentConsole() {
  const [title, setTitle] = useState('Checkout latency regression')
  const [description, setDescription] = useState(
    'Checkout latency and error rate increased. Investigate the incident using observable production signals.',
  )
  const [severity, setSeverity] = useState<Incident['severity']>('P2')
  const [service, setService] = useState('checkout')
  const [operationalMode, setOperationalMode] = useState(false)
  const [run, setRun] = useState<AgentRunView | null>(null)
  const [cost, setCost] = useState<RunCostSummary | null>(null)
  const [costState, setCostState] = useState<'idle' | 'loading' | 'ready' | 'missing' | 'error'>(
    'idle',
  )
  const [runLoading, setRunLoading] = useState(false)
  const [actionBusy, setActionBusy] = useState(false)
  const [pageError, setPageError] = useState<string | null>(null)
  const [metricsError, setMetricsError] = useState<string | null>(null)
  const [actor, setActor] = useState('incident-commander')

  const timeline = useMemo(() => (run ? buildTimeline(run) : []), [run])
  const compound = Boolean(run?.final_diagnosis?.secondary_root_causes.length)
  const pendingApproval = run?.approval?.decision === 'pending'

  useEffect(() => {
    if (!run || !pollingStatuses.has(run.status)) return undefined
    const runId = run.run_id
    const timer = window.setInterval(() => {
      void refreshRun(runId, true)
    }, 1500)
    return () => window.clearInterval(timer)
  }, [run?.run_id, run?.status])

  async function loadCost(runId: string) {
    setCostState('loading')
    setMetricsError(null)
    try {
      const summary = await getRunCostSummary(runId)
      setCost(summary)
      setCostState(summary ? 'ready' : 'missing')
    } catch (error) {
      setCost(null)
      setCostState('error')
      setMetricsError(errorMessage(error))
    }
  }

  function acceptRun(nextRun: AgentRunView) {
    setRun(nextRun)
    void loadCost(nextRun.run_id)
  }

  async function refreshRun(runId: string, quiet = false) {
    if (!quiet) setActionBusy(true)
    try {
      const nextRun = await getInvestigation(runId)
      acceptRun(nextRun)
      setPageError(null)
    } catch (error) {
      if (!quiet) setPageError(errorMessage(error))
    } finally {
      if (!quiet) setActionBusy(false)
    }
  }

  async function submitIncident(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setRunLoading(true)
    setPageError(null)
    setCost(null)
    setCostState('idle')

    const payload: StartInvestigationPayload = {
      incident: {
        title: title.trim(),
        description: description.trim(),
        severity,
        service: service.trim(),
        start_time: new Date().toISOString(),
        status: 'open',
      },
      operational_mode: operationalMode,
    }

    try {
      const nextRun = await startInvestigation(payload)
      acceptRun(nextRun)
    } catch (error) {
      setPageError(errorMessage(error))
    } finally {
      setRunLoading(false)
    }
  }

  async function resumeRun() {
    if (!run) return
    setActionBusy(true)
    setPageError(null)
    try {
      acceptRun(await resumeInvestigation(run.run_id))
    } catch (error) {
      setPageError(errorMessage(error))
    } finally {
      setActionBusy(false)
    }
  }

  async function submitApproval(decision: Exclude<ApprovalDecision, 'pending'>) {
    if (!run) return
    if (!actor.trim()) {
      setPageError('Decision actor is required.')
      return
    }
    setActionBusy(true)
    setPageError(null)
    try {
      acceptRun(await decideApproval(run.run_id, decision, actor.trim()))
    } catch (error) {
      setPageError(errorMessage(error))
    } finally {
      setActionBusy(false)
    }
  }

  function resetConsole() {
    setRun(null)
    setCost(null)
    setCostState('idle')
    setPageError(null)
    setMetricsError(null)
  }

  return (
    <div className="app-shell" data-testid="incident-console">
      <header className="topbar">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            OS
          </span>
          <div>
            <strong>OpsSentinel</strong>
            <span>Incident Console</span>
          </div>
        </div>
        <div className="topbar-meta">
          <span className="live-dot" aria-hidden="true" />
          research environment
        </div>
      </header>

      <main className="console-layout">
        <aside className="control-rail">
          <div>
            <p className="eyebrow">Phase 9 · Human-AI system</p>
            <h1>Investigate with evidence, not hidden state.</h1>
            <p className="rail-copy">
              Launch a bounded agent run, inspect its evidence and hypotheses independently, and
              keep human approval explicit for operational actions.
            </p>
          </div>

          <form className="incident-form" onSubmit={(event) => void submitIncident(event)}>
            <label>
              Incident title
              <input
                disabled={runLoading}
                maxLength={200}
                onChange={(event) => setTitle(event.target.value)}
                required
                value={title}
              />
            </label>
            <label>
              Service
              <input
                disabled={runLoading}
                maxLength={120}
                onChange={(event) => setService(event.target.value)}
                required
                value={service}
              />
            </label>
            <label>
              Severity
              <select
                disabled={runLoading}
                onChange={(event) => setSeverity(event.target.value as Incident['severity'])}
                value={severity}
              >
                {severityOptions.map((option) => (
                  <option key={option}>{option}</option>
                ))}
              </select>
            </label>
            <label>
              Observable symptoms
              <textarea
                disabled={runLoading}
                onChange={(event) => setDescription(event.target.value)}
                required
                rows={5}
                value={description}
              />
            </label>
            <label className="toggle-row">
              <input
                checked={operationalMode}
                disabled={runLoading}
                onChange={(event) => setOperationalMode(event.target.checked)}
                type="checkbox"
              />
              <span>
                Operational mode
                <small>Allows reversible actions only through the existing approval boundary.</small>
              </span>
            </label>
            <button
              className="primary-button full-width"
              data-testid="start-investigation"
              disabled={runLoading}
              type="submit"
            >
              {runLoading ? 'Starting investigation…' : 'Start investigation'}
            </button>
          </form>

          {run ? (
            <button className="ghost-button full-width" onClick={resetConsole} type="button">
              Clear current run
            </button>
          ) : null}
        </aside>

        <section className="workspace">
          {pageError ? (
            <div className="alert alert-critical" data-testid="console-error" role="alert">
              <strong>Console action failed</strong>
              <span>{pageError}</span>
            </div>
          ) : null}

          {!run ? (
            <div className="welcome-panel">
              <div className="radar" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <p className="eyebrow">Ready</p>
              <h2>Start with the incident humans can actually observe.</h2>
              <p>
                The console intentionally does not display benchmark ground truth, injected fault
                state, or simulator-only causal labels.
              </p>
              <div className="welcome-grid">
                <div>
                  <span>01</span>
                  <strong>Evidence</strong>
                  <p>Durable observations remain separate from model hypotheses.</p>
                </div>
                <div>
                  <span>02</span>
                  <strong>Human boundary</strong>
                  <p>Operational proposals remain pending until an explicit decision.</p>
                </div>
                <div>
                  <span>03</span>
                  <strong>Measurement</strong>
                  <p>Cost and latency show missing measurements as missing, never as zero.</p>
                </div>
              </div>
            </div>
          ) : (
            <>
              <section className="run-hero">
                <div>
                  <div className="run-kickers">
                    <span className={`status-pill status-${run.status}`} data-testid="run-status">
                      {statusLabel(run.status)}
                    </span>
                    <span className="severity-pill">{run.incident.severity}</span>
                    {compound ? (
                      <span className="compound-pill" data-testid="compound-badge">
                        compound RCA
                      </span>
                    ) : null}
                  </div>
                  <h2>{run.incident.title}</h2>
                  <p>{run.incident.description}</p>
                </div>
                <div className="run-identity">
                  <span>Run ID</span>
                  <code>{run.run_id}</code>
                  <button
                    className="text-button"
                    disabled={actionBusy}
                    onClick={() => void refreshRun(run.run_id)}
                    type="button"
                  >
                    Refresh
                  </button>
                </div>
              </section>

              {run.status === 'failed' || run.status === 'budget_exhausted' ? (
                <div className="alert alert-critical" data-testid="agent-failure-state">
                  <strong>
                    {run.status === 'failed' ? 'Agent run failed' : 'Investigation budget exhausted'}
                  </strong>
                  <span>{run.stop_reason ?? run.budget.exhausted_reason ?? 'No stop reason recorded.'}</span>
                </div>
              ) : null}

              {run.approval?.decision === 'rejected' ? (
                <div className="alert alert-warning" data-testid="rejected-state">
                  <strong>Operational action rejected</strong>
                  <span>
                    The investigation record is preserved; no rejected action is treated as executed.
                  </span>
                </div>
              ) : null}

              {run.status === 'completed' ? (
                <div className="alert alert-success" data-testid="completed-state">
                  <strong>Investigation completed</strong>
                  <span>
                    {run.verification.status === 'passed'
                      ? 'The recorded verification passed.'
                      : `Verification: ${statusLabel(run.verification.status)}.`}
                  </span>
                </div>
              ) : null}

              <div className="metric-grid" aria-label="Run summary">
                <Metric label="Confidence" value={formatPercent(run.confidence)} />
                <Metric label="Steps" value={`${run.budget.steps_used}/${run.budget.max_steps}`} />
                <Metric
                  label="Tool calls"
                  value={`${run.budget.tool_calls_used}/${run.budget.max_tool_calls}`}
                />
                <Metric
                  label="Token budget"
                  value={`${run.budget.tokens_used.toLocaleString()}/${run.budget.token_budget.toLocaleString()}`}
                />
              </div>

              {pendingApproval && run.approval ? (
                <section className="approval-card" data-testid="approval-card">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Human approval required</p>
                      <h3>{run.approval.action.description}</h3>
                    </div>
                    <span className={`risk-badge risk-${run.approval.action.risk_level.toLowerCase()}`}>
                      {run.approval.action.risk_level}
                    </span>
                  </div>
                  <p>{run.approval.why_proposed}</p>
                  <div className="approval-grid">
                    <div>
                      <span>Expected benefit</span>
                      <p>{run.approval.expected_benefit}</p>
                    </div>
                    <div>
                      <span>Possible risk</span>
                      <p>{run.approval.possible_risk}</p>
                    </div>
                    <div>
                      <span>Rollback</span>
                      <p>{run.approval.rollback_strategy}</p>
                    </div>
                  </div>
                  <label className="actor-field">
                    Decision actor
                    <input
                      disabled={actionBusy}
                      maxLength={120}
                      onChange={(event) => setActor(event.target.value)}
                      value={actor}
                    />
                  </label>
                  <div className="approval-actions">
                    <button
                      className="approve-button"
                      data-testid="approve-button"
                      disabled={actionBusy}
                      onClick={() => void submitApproval('approved')}
                      type="button"
                    >
                      Approve action
                    </button>
                    <button
                      className="reject-button"
                      data-testid="reject-button"
                      disabled={actionBusy}
                      onClick={() => void submitApproval('rejected')}
                      type="button"
                    >
                      Reject action
                    </button>
                    <button
                      className="ghost-button"
                      disabled={actionBusy}
                      onClick={() => void submitApproval('abandoned')}
                      type="button"
                    >
                      Abandon
                    </button>
                  </div>
                </section>
              ) : null}

              {run.status === 'paused' && !pendingApproval ? (
                <div className="paused-control">
                  <div>
                    <strong>Investigation paused</strong>
                    <span>Next node: {statusLabel(run.next_node)}</span>
                  </div>
                  <button
                    className="primary-button"
                    disabled={actionBusy}
                    onClick={() => void resumeRun()}
                    type="button"
                  >
                    Resume investigation
                  </button>
                </div>
              ) : null}

              <div className="workspace-grid">
                <section className="panel timeline-panel">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Investigation timeline</p>
                      <h3>What happened, in observed order</h3>
                    </div>
                    <span>{timeline.length} events</span>
                  </div>
                  <div className="timeline" data-testid="investigation-timeline">
                    {timeline.map((item) => (
                      <article className={`timeline-item tone-${item.tone ?? 'neutral'}`} key={item.id}>
                        <div className="timeline-dot" aria-hidden="true" />
                        <div>
                          <div className="timeline-meta">
                            <span>{item.kind}</span>
                            <time>{formatDate(item.timestamp)}</time>
                          </div>
                          <strong>{item.title}</strong>
                          <p>{item.detail}</p>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>

                <div className="panel-stack">
                  <section className="panel" data-testid="evidence-panel">
                    <div className="section-heading">
                      <div>
                        <p className="eyebrow">Evidence</p>
                        <h3>Grounded observations</h3>
                      </div>
                      <span>{run.evidence.length}</span>
                    </div>
                    {run.evidence.length === 0 ? (
                      <EmptyState>No evidence has been stored yet.</EmptyState>
                    ) : (
                      <div className="card-list">
                        {run.evidence.map((evidence) => (
                          <article className="evidence-card" key={evidence.id}>
                            <div className="card-meta">
                              <span>{evidence.evidence_type}</span>
                              <span>{evidence.service ?? 'cross-service'}</span>
                              <span>{Math.round(evidence.reliability * 100)}% reliable</span>
                            </div>
                            <p>{evidence.observation}</p>
                            <small>
                              {evidence.source} · {formatDate(evidence.timestamp)}
                            </small>
                          </article>
                        ))}
                      </div>
                    )}
                  </section>

                  <section className="panel" data-testid="hypotheses-panel">
                    <div className="section-heading">
                      <div>
                        <p className="eyebrow">Hypotheses</p>
                        <h3>Model beliefs, kept separate</h3>
                      </div>
                      <span>{run.hypotheses.length}</span>
                    </div>
                    {run.hypotheses.length === 0 ? (
                      <EmptyState>No hypotheses have been recorded yet.</EmptyState>
                    ) : (
                      <div className="card-list">
                        {run.hypotheses
                          .slice()
                          .sort((left, right) => right.confidence - left.confidence)
                          .map((hypothesis) => (
                            <article className="hypothesis-card" key={hypothesis.id}>
                              <div className="hypothesis-head">
                                <span className={`hypothesis-status hypothesis-${hypothesis.status}`}>
                                  {hypothesis.status}
                                </span>
                                <strong>{formatPercent(hypothesis.confidence)}</strong>
                              </div>
                              <p>{hypothesis.description}</p>
                              <code>{hypothesis.root_cause_code}</code>
                              <div className="evidence-links">
                                <span>+ {hypothesis.supporting_evidence.length} supporting</span>
                                <span>− {hypothesis.contradicting_evidence.length} contradicting</span>
                              </div>
                            </article>
                          ))}
                      </div>
                    )}
                  </section>
                </div>
              </div>

              <div className="workspace-grid lower-grid">
                <section className="panel">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Investigation plan</p>
                      <h3>{run.plan?.summary ?? 'Plan not generated yet'}</h3>
                    </div>
                  </div>
                  {run.plan ? (
                    <ol className="plan-list">
                      {run.plan.steps.map((step) => (
                        <li className={step.completed ? 'plan-complete' : ''} key={step.id}>
                          <span className="plan-check" aria-hidden="true">
                            {step.completed ? '✓' : '·'}
                          </span>
                          <div>
                            <strong>{step.objective}</strong>
                            <p>{step.rationale}</p>
                            <small>{step.tool}</small>
                          </div>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <EmptyState>The agent has not persisted a plan yet.</EmptyState>
                  )}
                </section>

                <section className="panel" data-testid="diagnosis-panel">
                  <div className="section-heading">
                    <div>
                      <p className="eyebrow">Diagnosis & verification</p>
                      <h3>
                        {run.final_diagnosis?.primary_root_cause ?? 'No final diagnosis yet'}
                      </h3>
                    </div>
                    {run.diagnosis_code ? <code>{run.diagnosis_code}</code> : null}
                  </div>
                  {run.final_diagnosis ? (
                    <>
                      <div className="diagnosis-confidence">
                        <span>Diagnosis confidence</span>
                        <strong>{formatPercent(run.final_diagnosis.confidence)}</strong>
                      </div>
                      {run.final_diagnosis.secondary_root_causes.length > 0 ? (
                        <div className="secondary-causes">
                          <span>Secondary root causes</span>
                          <ul>
                            {run.final_diagnosis.secondary_root_causes.map((cause) => (
                              <li key={cause}>{cause}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      <div className="recommendations">
                        <span>Recommended actions</span>
                        {run.final_diagnosis.recommended_actions.length > 0 ? (
                          <ul>
                            {run.final_diagnosis.recommended_actions.map((action) => (
                              <li key={action}>{action}</li>
                            ))}
                          </ul>
                        ) : (
                          <p>No recommendations recorded.</p>
                        )}
                      </div>
                    </>
                  ) : (
                    <EmptyState>The final diagnosis appears only after grounded investigation.</EmptyState>
                  )}
                  <div className={`verification verification-${run.verification.status}`}>
                    <span>{statusLabel(run.verification.status)}</span>
                    <p>{run.verification.summary}</p>
                  </div>
                </section>
              </div>

              <section className="panel measurement-panel" data-testid="measurement-panel">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">Phase 9 measurement</p>
                    <h3>Cost, tokens & latency</h3>
                  </div>
                  <span>
                    {costState === 'loading'
                      ? 'Refreshing…'
                      : costState === 'missing'
                        ? 'Summary not recorded'
                        : costState === 'error'
                          ? 'Summary unavailable'
                          : cost?.model ?? 'Awaiting data'}
                  </span>
                </div>
                {metricsError ? <p className="metrics-error">{metricsError}</p> : null}
                {cost ? (
                  <div className="measurement-grid">
                    <Metric label="Estimated cost" value={formatCost(cost.total_estimated_cost)} />
                    <Metric label="Total tokens" value={cost.total_tokens.toLocaleString()} />
                    <Metric label="Retrieval depth" value={cost.retrieval_depth.toLocaleString()} />
                    <Metric
                      label="Model latency p50 / p95"
                      value={`${formatLatency(cost.model_latency.p50_ms)} / ${formatLatency(cost.model_latency.p95_ms)}`}
                      hint={`${cost.model_latency.count} measured calls`}
                    />
                    <Metric
                      label="Tool latency p50 / p95"
                      value={`${formatLatency(cost.tool_latency.p50_ms)} / ${formatLatency(cost.tool_latency.p95_ms)}`}
                      hint={`${cost.tool_latency.count} measured calls`}
                    />
                    <Metric
                      label="Time to first step"
                      value={formatMilliseconds(cost.time_to_first_investigation_step_ms)}
                    />
                    <Metric
                      label="Time to diagnosis"
                      value={formatMilliseconds(cost.time_to_diagnosis_ms)}
                    />
                    <div data-testid="metric-time-to-verified-resolution">
                      <Metric
                        label="Time to verified resolution"
                        value={formatMilliseconds(cost.time_to_verified_resolution_ms)}
                      />
                    </div>
                  </div>
                ) : (
                  <EmptyState>
                    {costState === 'loading'
                      ? 'Loading persisted measurement summary…'
                      : 'No persisted measurement summary is available for this run.'}
                  </EmptyState>
                )}
              </section>
            </>
          )}
        </section>
      </main>
    </div>
  )
}

export default function App() {
  return traceProofEnabled ? <TraceProof /> : <IncidentConsole />
}
