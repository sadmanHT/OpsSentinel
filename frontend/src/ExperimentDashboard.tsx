import { useEffect, useMemo, useState } from 'react'

import {
  getExperimentDashboard,
  type ExperimentDashboardResponse,
  type ExperimentRunSummary,
} from './experiments'
import './experiment-dashboard.css'

function formatDate(value: string | null): string {
  if (!value) return 'Not recorded'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatPercent(value: number | null): string {
  return value === null ? 'Not measured' : `${Math.round(value * 100)}%`
}

function formatNumber(value: number | null, digits = 1): string {
  return value === null ? 'Not measured' : value.toFixed(digits)
}

function renderSetting(value: unknown): string {
  if (value === null || value === undefined) return 'Not recorded'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return JSON.stringify(value)
}

function metricTone(value: number | null, higherIsBetter = true): string {
  if (value === null) return 'metric-neutral'
  const good = higherIsBetter ? value >= 0.8 : value === 0
  return good ? 'metric-positive' : 'metric-attention'
}

function ExperimentCard({ run }: { run: ExperimentRunSummary }) {
  const configEntries = Object.entries(run.configuration)
  const retrievalEntries = Object.entries(run.retrieval_settings)
  const failures = Object.entries(run.failure_categories).sort((left, right) => right[1] - left[1])

  return (
    <article className="experiment-card" data-testid="experiment-run-card">
      <header className="experiment-card-header">
        <div>
          <p className="experiment-kicker">Evaluation run</p>
          <h2>{run.architecture_version}</h2>
          <code>{run.evaluation_run_id}</code>
        </div>
        <div className="experiment-card-meta">
          <span>{run.dataset_version}</span>
          <span>{run.model}</span>
          <span>seed {run.seed}</span>
        </div>
      </header>

      <section className="experiment-metric-grid" aria-label="Evaluation metrics">
        <div className={metricTone(run.metrics.correctness_mean)} data-testid="metric-correctness">
          <span>Correctness</span>
          <strong>{formatPercent(run.metrics.correctness_mean)}</strong>
        </div>
        <div
          className={metricTone(run.metrics.primary_root_cause_accuracy_mean)}
          data-testid="metric-root-cause"
        >
          <span>Root-cause accuracy</span>
          <strong>{formatPercent(run.metrics.primary_root_cause_accuracy_mean)}</strong>
        </div>
        <div className={metricTone(run.metrics.evidence_precision_mean)}>
          <span>Evidence precision</span>
          <strong>{formatPercent(run.metrics.evidence_precision_mean)}</strong>
        </div>
        <div className={metricTone(run.metrics.evidence_recall_mean)}>
          <span>Evidence recall</span>
          <strong>{formatPercent(run.metrics.evidence_recall_mean)}</strong>
        </div>
        <div className="metric-neutral">
          <span>Tool calls / scenario</span>
          <strong>{formatNumber(run.metrics.total_tool_calls_mean)}</strong>
        </div>
        <div className={metricTone(run.metrics.unsafe_action_attempts_total, false)}>
          <span>Unsafe attempts</span>
          <strong>{formatNumber(run.metrics.unsafe_action_attempts_total, 0)}</strong>
        </div>
      </section>

      <div className="experiment-detail-grid">
        <section>
          <h3>Run coverage</h3>
          <dl>
            <div>
              <dt>Scenarios</dt>
              <dd>{run.scenario_count}</dd>
            </div>
            <div>
              <dt>Linked agent runs</dt>
              <dd>{run.linked_agent_run_count}</dd>
            </div>
            <div>
              <dt>Tool budget</dt>
              <dd>{run.tool_budget ?? 'Not recorded'}</dd>
            </div>
            <div>
              <dt>Created</dt>
              <dd>{formatDate(run.created_at)}</dd>
            </div>
          </dl>
        </section>

        <section>
          <h3>Versioned experiment</h3>
          <dl>
            <div>
              <dt>Prompt</dt>
              <dd>{run.prompt_version ?? 'Not recorded'}</dd>
            </div>
            <div>
              <dt>Scenarios</dt>
              <dd>{run.scenario_version ?? 'Not recorded'}</dd>
            </div>
            <div>
              <dt>Evaluator</dt>
              <dd>{run.evaluation_version ?? 'Not recorded'}</dd>
            </div>
            <div>
              <dt>Recorded</dt>
              <dd>{formatDate(run.recorded_at)}</dd>
            </div>
          </dl>
        </section>
      </div>

      <div className="experiment-config-grid">
        <section>
          <h3>Configuration</h3>
          {configEntries.length ? (
            <div className="config-chips">
              {configEntries.map(([key, value]) => (
                <span key={key}>
                  <b>{key}</b> {renderSetting(value)}
                </span>
              ))}
            </div>
          ) : (
            <p className="experiment-empty-inline">No configuration fields persisted.</p>
          )}
        </section>
        <section>
          <h3>Retrieval</h3>
          {retrievalEntries.length ? (
            <div className="config-chips">
              {retrievalEntries.map(([key, value]) => (
                <span key={key}>
                  <b>{key}</b> {renderSetting(value)}
                </span>
              ))}
            </div>
          ) : (
            <p className="experiment-empty-inline">No retrieval settings persisted.</p>
          )}
        </section>
      </div>

      <section className="failure-section">
        <h3>Failure categories</h3>
        {failures.length ? (
          <ul data-testid="experiment-failures">
            {failures.map(([category, count]) => (
              <li key={category}>
                <span>{category.replaceAll('_', ' ')}</span>
                <strong>{count}</strong>
              </li>
            ))}
          </ul>
        ) : (
          <p className="experiment-empty-inline">No failure categories persisted for this run.</p>
        )}
      </section>
    </article>
  )
}

export default function ExperimentDashboard() {
  const [dashboard, setDashboard] = useState<ExperimentDashboardResponse | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setState('loading')
    setError(null)
    try {
      setDashboard(await getExperimentDashboard())
      setState('ready')
    } catch (failure) {
      setDashboard(null)
      setError(failure instanceof Error ? failure.message : String(failure))
      setState('error')
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  const scenarioTotal = useMemo(
    () => dashboard?.runs.reduce((total, run) => total + run.scenario_count, 0) ?? 0,
    [dashboard],
  )

  return (
    <div className="experiment-shell" data-testid="experiment-dashboard">
      <header className="experiment-topbar">
        <a className="experiment-brand" href="/">
          <span aria-hidden="true">OS</span>
          <div>
            <strong>OpsSentinel</strong>
            <small>Experiment Dashboard</small>
          </div>
        </a>
        <a className="console-link" href="/">
          Incident Console
        </a>
      </header>

      <main className="experiment-main">
        <section className="experiment-hero">
          <div>
            <p className="experiment-kicker">Phase 9 · Persisted evaluation evidence</p>
            <h1>Compare agent experiments from the database, not from screenshots.</h1>
            <p>
              Each card is built from persisted evaluation runs, scenario scores, and experiment
              metadata. Missing measurements stay missing; real zeros stay zero.
            </p>
          </div>
          <button disabled={state === 'loading'} onClick={() => void refresh()} type="button">
            {state === 'loading' ? 'Loading…' : 'Refresh'}
          </button>
        </section>

        <section className="experiment-summary" aria-label="Experiment summary">
          <div>
            <span>Persisted runs</span>
            <strong data-testid="experiment-run-count">{dashboard?.run_count ?? '—'}</strong>
          </div>
          <div>
            <span>Scenarios represented</span>
            <strong>{dashboard ? scenarioTotal : '—'}</strong>
          </div>
          <div>
            <span>Source</span>
            <strong>Evaluation DB</strong>
          </div>
        </section>

        {state === 'error' ? (
          <section className="experiment-error" role="alert">
            <h2>Experiment data unavailable</h2>
            <p>{error}</p>
          </section>
        ) : null}

        {state === 'loading' && !dashboard ? (
          <section className="experiment-loading" data-testid="experiment-loading">
            Reading persisted evaluation records…
          </section>
        ) : null}

        {state === 'ready' && dashboard?.runs.length === 0 ? (
          <section className="experiment-empty" data-testid="experiment-empty">
            <h2>No persisted evaluation runs</h2>
            <p>Run EvaluationLab or a Phase 9 experiment campaign to populate this dashboard.</p>
          </section>
        ) : null}

        <section className="experiment-list">
          {dashboard?.runs.map((run) => (
            <ExperimentCard key={run.evaluation_run_id} run={run} />
          ))}
        </section>
      </main>
    </div>
  )
}
