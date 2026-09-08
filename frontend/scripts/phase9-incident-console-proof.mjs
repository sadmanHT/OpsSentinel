import { writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

const outputPath =
  process.env.OPSSENTINEL_INCIDENT_CONSOLE_ARTIFACT ?? 'phase9-incident-console-browser.json'
const url = process.env.OPSSENTINEL_INCIDENT_CONSOLE_URL ?? 'http://127.0.0.1:5173/'

const incidentId = '11111111-1111-4111-8111-111111111111'
const runId = '22222222-2222-4222-8222-222222222222'
const evidenceId = '33333333-3333-4333-8333-333333333333'
const hypothesisId = '44444444-4444-4444-8444-444444444444'
const approvalId = '55555555-5555-4555-8555-555555555555'
const toolCallId = '66666666-6666-4666-8666-666666666666'
const startedAt = '2026-09-08T14:00:00Z'

function budget(overrides = {}) {
  return {
    max_steps: 20,
    max_tool_calls: 15,
    max_repeated_identical_calls: 2,
    time_limit_seconds: 120,
    token_budget: 32000,
    cost_budget: 0,
    steps_used: 8,
    tool_calls_used: 2,
    tokens_used: 0,
    cost_used: 0,
    repeated_calls: {},
    exhausted_reason: null,
    ...overrides,
  }
}

function baseRun(overrides = {}) {
  return {
    run_id: runId,
    incident: {
      id: incidentId,
      title: 'Checkout latency regression',
      description: 'Checkout latency and error rate increased.',
      severity: 'P2',
      service: 'checkout',
      start_time: startedAt,
      status: 'investigating',
      scenario_id: null,
    },
    status: 'paused',
    next_node: 'recommend',
    operational_mode: true,
    operation_stage: 'wait_approval',
    plan: {
      summary: 'Correlate public service evidence before recommending action.',
      steps: [
        {
          id: 'step-1',
          objective: 'Inspect checkout metrics',
          tool: 'get_service_metrics',
          arguments: {},
          rationale: 'Validate the user-visible regression.',
          required: true,
          completed: true,
        },
      ],
    },
    evidence: [
      {
        id: evidenceId,
        incident_id: incidentId,
        source: 'prometheus',
        evidence_type: 'metric',
        service: 'checkout',
        timestamp: '2026-09-08T14:00:04Z',
        observation: 'Checkout p95 latency rose above the recent baseline.',
        raw_reference: 'metric://checkout/p95',
        reliability: 0.98,
      },
    ],
    hypotheses: [
      {
        id: hypothesisId,
        description: 'Checkout is blocked on a saturated downstream database pool.',
        root_cause_code: 'checkout.database_pool_saturation',
        confidence: 0.82,
        supporting_evidence: [evidenceId],
        contradicting_evidence: [],
        first_possible_cause_time: '2026-09-08T13:59:50Z',
        effect_time: '2026-09-08T14:00:00Z',
        status: 'active',
      },
    ],
    tool_history: [
      {
        id: toolCallId,
        tool_name: 'get_service_metrics',
        arguments: { service: 'checkout' },
        started_at: '2026-09-08T14:00:02Z',
        completed_at: '2026-09-08T14:00:03Z',
        status: 'succeeded',
        result_reference: 'metric://checkout/p95',
        risk_level: 'R0',
      },
    ],
    confidence: 0.82,
    budget: budget(),
    proposed_action: {
      description: 'Restart the reversible checkout sandbox worker.',
      risk_level: 'R2',
      rationale: 'Restore checkout capacity while preserving a rollback path.',
      evidence_ids: [evidenceId],
      tool: 'restart_service',
      arguments: { service: 'checkout' },
      expected_benefit: 'Restore checkout request capacity.',
      possible_risk: 'In-flight sandbox requests may be interrupted.',
      rollback_strategy: 'Restore the prior sandbox process state.',
    },
    approval: {
      id: approvalId,
      action: {
        description: 'Restart the reversible checkout sandbox worker.',
        risk_level: 'R2',
        rationale: 'Restore checkout capacity while preserving a rollback path.',
        evidence_ids: [evidenceId],
        tool: 'restart_service',
        arguments: { service: 'checkout' },
        expected_benefit: 'Restore checkout request capacity.',
        possible_risk: 'In-flight sandbox requests may be interrupted.',
        rollback_strategy: 'Restore the prior sandbox process state.',
      },
      why_proposed: 'Observable evidence supports a reversible checkout recovery action.',
      evidence_ids: [evidenceId],
      expected_benefit: 'Restore checkout request capacity.',
      possible_risk: 'In-flight sandbox requests may be interrupted.',
      rollback_strategy: 'Restore the prior sandbox process state.',
      decision: 'pending',
      created_at: '2026-09-08T14:00:07Z',
      decided_at: null,
      decided_by: null,
    },
    verification: {
      status: 'not_run',
      summary: 'No verification has been run.',
      evidence_ids: [],
    },
    failures: [],
    diagnosis_code: null,
    final_diagnosis: null,
    report: null,
    stop_reason: null,
    ...overrides,
  }
}

const pendingRun = baseRun()

const rejectedCompletedRun = baseRun({
  status: 'completed',
  next_node: 'end',
  operation_stage: 'complete',
  confidence: 0.9,
  approval: {
    ...pendingRun.approval,
    decision: 'rejected',
    decided_at: '2026-09-08T14:00:11Z',
    decided_by: 'incident-commander',
  },
  diagnosis_code: 'checkout.database_pool_saturation',
  final_diagnosis: {
    primary_root_cause: 'Checkout database pool saturation',
    secondary_root_causes: ['Inventory retry amplification'],
    confidence: 0.9,
    evidence_ids: [evidenceId],
    recommended_actions: ['Increase database pool headroom before the next load test.'],
    verification_status: 'inconclusive',
  },
  verification: {
    status: 'inconclusive',
    summary: 'The proposed operational action was rejected, so no post-action verification ran.',
    evidence_ids: [],
  },
  report: {
    run_id: runId,
    status: 'completed',
    root_cause_code: 'checkout.database_pool_saturation',
    diagnosis: {
      primary_root_cause: 'Checkout database pool saturation',
      secondary_root_causes: ['Inventory retry amplification'],
      confidence: 0.9,
      evidence_ids: [evidenceId],
      recommended_actions: ['Increase database pool headroom before the next load test.'],
      verification_status: 'inconclusive',
    },
    claims: [
      {
        statement: 'Checkout latency increased during the observed interval.',
        evidence_ids: [evidenceId],
      },
    ],
    proposed_action: pendingRun.proposed_action,
    verification: {
      status: 'inconclusive',
      summary: 'The proposed operational action was rejected, so no post-action verification ran.',
      evidence_ids: [],
    },
    generated_at: '2026-09-08T14:00:12Z',
  },
})

const failedRun = baseRun({
  run_id: '77777777-7777-4777-8777-777777777777',
  status: 'failed',
  next_node: 'end',
  operational_mode: false,
  operation_stage: 'none',
  evidence: [],
  hypotheses: [],
  tool_history: [],
  confidence: 0,
  budget: budget({ steps_used: 1, tool_calls_used: 0 }),
  proposed_action: null,
  approval: null,
  failures: [
    {
      tool: 'model_provider',
      code: 'provider_unavailable',
      message: 'The configured model provider was unavailable.',
      retryable: true,
      attempt: 2,
      recorded_at: '2026-09-08T14:05:02Z',
    },
  ],
  verification: {
    status: 'not_run',
    summary: 'No verification has been run.',
    evidence_ids: [],
  },
  diagnosis_code: null,
  final_diagnosis: null,
  report: null,
  stop_reason: 'model provider unavailable after bounded retries',
})

const costSummary = {
  run_id: runId,
  status: 'paused',
  model: 'deterministic-research-provider',
  model_execution_count: 5,
  failed_model_execution_count: 0,
  usage_breakdown_available: true,
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  provider_estimated_cost: 0,
  total_estimated_cost: 0,
  tool_call_count: 2,
  retrieval_depth: 0,
  model_latency: { count: 5, p50_ms: 18.4, p95_ms: 31.2 },
  tool_latency: { count: 2, p50_ms: 44.1, p95_ms: 52.8 },
  time_to_first_investigation_step_ms: 12.5,
  time_to_diagnosis_ms: 410.2,
  time_to_verified_resolution_ms: null,
}

function assertIncludes(actual, expected, label) {
  if (!actual.includes(expected)) {
    throw new Error(`${label} missing ${JSON.stringify(expected)}: ${JSON.stringify(actual)}`)
  }
}

const browserErrors = []
let startCount = 0
let currentRun = pendingRun
const browser = await chromium.launch({ headless: true })

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.on('pageerror', (error) => browserErrors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`)
  })

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const parsed = new URL(request.url())
    const path = parsed.pathname

    if (path === '/api/agent/runs' && request.method() === 'POST') {
      startCount += 1
      currentRun = startCount === 1 ? pendingRun : failedRun
      await new Promise((resolve) => setTimeout(resolve, 220))
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(currentRun),
      })
      return
    }

    if (path.endsWith('/approval') && request.method() === 'POST') {
      currentRun = rejectedCompletedRun
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(currentRun),
      })
      return
    }

    if (path.includes('/api/observability/runs/') && path.endsWith('/cost')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...costSummary,
          run_id: currentRun.run_id,
          status: currentRun.status,
        }),
      })
      return
    }

    if (path.includes('/api/agent/runs/') && request.method() === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(currentRun),
      })
      return
    }

    await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"not mocked"}' })
  })

  await page.goto(url, { waitUntil: 'networkidle' })
  await page.getByTestId('incident-console').waitFor()

  const firstStart = page.getByTestId('start-investigation').click()
  await page.waitForFunction(() => {
    return document.querySelector('[data-testid="start-investigation"]')?.textContent?.includes('Starting investigation')
  })
  const loadingStateVerified = true
  await firstStart

  await page.waitForFunction(() => {
    return document.querySelector('[data-testid="run-status"]')?.textContent?.includes('paused')
  })
  await page.getByTestId('approval-card').waitFor()

  const evidenceText = (await page.getByTestId('evidence-panel').textContent()) ?? ''
  const hypothesesText = (await page.getByTestId('hypotheses-panel').textContent()) ?? ''
  assertIncludes(evidenceText, 'Checkout p95 latency rose above the recent baseline.', 'evidence panel')
  assertIncludes(
    hypothesesText,
    'Checkout is blocked on a saturated downstream database pool.',
    'hypotheses panel',
  )

  await page.waitForFunction(() => {
    return document.querySelector('[data-testid="metric-time-to-verified-resolution"]')?.textContent?.includes('Not measured')
  })
  const measurementText = (await page.getByTestId('measurement-panel').textContent()) ?? ''
  assertIncludes(measurementText, '$0.0000', 'zero-cost measurement')
  assertIncludes(measurementText, 'Not measured', 'missing latency measurement')

  await page.getByTestId('reject-button').click()
  await page.getByTestId('rejected-state').waitFor()
  await page.getByTestId('completed-state').waitFor()
  await page.getByTestId('compound-badge').waitFor()

  const diagnosisText = (await page.getByTestId('diagnosis-panel').textContent()) ?? ''
  assertIncludes(diagnosisText, 'Checkout database pool saturation', 'diagnosis panel')
  assertIncludes(diagnosisText, 'Inventory retry amplification', 'compound diagnosis')

  await page.getByRole('button', { name: 'Clear current run' }).click()
  await page.getByTestId('start-investigation').click()
  await page.getByTestId('agent-failure-state').waitFor()
  const failureText = (await page.getByTestId('agent-failure-state').textContent()) ?? ''
  assertIncludes(failureText, 'model provider unavailable after bounded retries', 'agent failure state')

  if (browserErrors.length > 0) {
    throw new Error(`browser emitted errors: ${browserErrors.join('; ')}`)
  }

  await writeFile(
    outputPath,
    `${JSON.stringify(
      {
        loading_state_verified: loadingStateVerified,
        evidence_hypothesis_separation_verified: true,
        approval_state_verified: true,
        rejected_state_verified: true,
        completed_state_verified: true,
        compound_state_verified: true,
        agent_failure_state_verified: true,
        missing_measurement_rendered_as_missing: true,
        zero_cost_preserved_as_zero: true,
        browser_errors: browserErrors,
      },
      null,
      2,
    )}\n`,
    'utf8',
  )
} finally {
  await browser.close()
}
