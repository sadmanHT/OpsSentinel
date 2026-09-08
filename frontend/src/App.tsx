import { useState } from 'react'

import { browserTracingEnabled, startInvestigation } from './observability'

const traceProofEnabled = browserTracingEnabled()

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

export default function App() {
  const [proofStatus, setProofStatus] = useState('idle')
  const [traceId, setTraceId] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  async function runTraceProof() {
    setProofStatus('running')
    setErrorMessage(null)
    try {
      const result = await startInvestigation(traceProofPayload())
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
    <main style={{ fontFamily: 'system-ui', maxWidth: 900, margin: '4rem auto', padding: '0 1.5rem' }}>
      <p style={{ textTransform: 'uppercase', letterSpacing: '0.12em', fontWeight: 700 }}>
        OpsSentinel
      </p>
      <h1>Autonomous incident-response research platform</h1>
      <p>
        Phase 1 establishes reproducible contracts, persistence, CI, and a clean foundation for
        ChaosLab and the agent runtime.
      </p>

      {traceProofEnabled ? (
        <section aria-label="Phase 9.4 trace proof" style={{ marginTop: '2rem' }}>
          <h2>Phase 9.4 distributed trace proof</h2>
          <p>
            Starts one bounded checkout investigation and pauses after the first stored evidence so
            browser, API, agent, MCP, and simulator spans can be verified under one trace ID.
          </p>
          <button
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
      ) : null}
    </main>
  )
}
