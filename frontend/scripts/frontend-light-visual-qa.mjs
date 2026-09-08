import { chromium } from 'playwright'

const incidentId = '11111111-1111-4111-8111-111111111111'
const runId = '22222222-2222-4222-8222-222222222222'
const evidenceId = '33333333-3333-4333-8333-333333333333'

const run = {
  run_id: runId,
  incident: {
    id: incidentId,
    title: 'Checkout latency regression',
    description: 'Checkout latency and error rate increased after a routine traffic shift.',
    severity: 'P2',
    service: 'checkout',
    start_time: '2026-09-08T14:00:00Z',
    status: 'investigating',
    scenario_id: null,
  },
  status: 'completed',
  next_node: 'end',
  operational_mode: true,
  operation_stage: 'complete',
  plan: {
    summary: 'Correlate service evidence before recommending action.',
    steps: [
      { id: 'step-1', objective: 'Inspect checkout latency', tool: 'get_service_metrics', arguments: {}, rationale: 'Confirm the user-visible regression.', required: true, completed: true },
      { id: 'step-2', objective: 'Check database saturation', tool: 'get_database_metrics', arguments: {}, rationale: 'Test the leading dependency hypothesis.', required: true, completed: true },
      { id: 'step-3', objective: 'Review inventory retries', tool: 'search_logs', arguments: {}, rationale: 'Account for remaining cross-service symptoms.', required: true, completed: true },
    ],
  },
  evidence: [
    { id: evidenceId, incident_id: incidentId, source: 'prometheus', evidence_type: 'metric', service: 'checkout', timestamp: '2026-09-08T14:00:04Z', observation: 'Checkout p95 latency rose above the recent baseline.', raw_reference: 'metric://checkout/p95', reliability: 0.98 },
    { id: '33333333-3333-4333-8333-333333333334', incident_id: incidentId, source: 'logs', evidence_type: 'log', service: 'inventory', timestamp: '2026-09-08T14:00:05Z', observation: 'Inventory retries amplified during the same interval.', raw_reference: 'log://inventory/retries', reliability: 0.94 },
  ],
  hypotheses: [
    { id: '44444444-4444-4444-8444-444444444444', description: 'Checkout is blocked on a saturated downstream database pool.', root_cause_code: 'checkout.database_pool_saturation', confidence: 0.9, supporting_evidence: [evidenceId], contradicting_evidence: [], first_possible_cause_time: '2026-09-08T13:59:50Z', effect_time: '2026-09-08T14:00:00Z', status: 'confirmed' },
    { id: '44444444-4444-4444-8444-444444444445', description: 'Inventory retries are a secondary contributor to request pressure.', root_cause_code: 'inventory.retry_amplification', confidence: 0.74, supporting_evidence: ['33333333-3333-4333-8333-333333333334'], contradicting_evidence: [], first_possible_cause_time: '2026-09-08T13:59:40Z', effect_time: '2026-09-08T14:00:00Z', status: 'confirmed' },
  ],
  tool_history: [
    { id: '66666666-6666-4666-8666-666666666666', tool_name: 'get_service_metrics', arguments: { service: 'checkout' }, started_at: '2026-09-08T14:00:02Z', completed_at: '2026-09-08T14:00:03Z', status: 'succeeded', result_reference: 'metric://checkout/p95', risk_level: 'R0' },
    { id: '66666666-6666-4666-8666-666666666667', tool_name: 'search_logs', arguments: { service: 'inventory' }, started_at: '2026-09-08T14:00:04Z', completed_at: '2026-09-08T14:00:05Z', status: 'succeeded', result_reference: 'log://inventory/retries', risk_level: 'R0' },
  ],
  confidence: 0.9,
  budget: { max_steps: 20, max_tool_calls: 15, max_repeated_identical_calls: 2, time_limit_seconds: 120, token_budget: 32000, cost_budget: 0, steps_used: 9, tool_calls_used: 3, tokens_used: 0, cost_used: 0, repeated_calls: {}, exhausted_reason: null },
  proposed_action: null,
  approval: null,
  verification: { status: 'passed', summary: 'The recorded verification passed after the investigation completed.', evidence_ids: [evidenceId] },
  failures: [],
  diagnosis_code: 'checkout.database_pool_saturation',
  final_diagnosis: { primary_root_cause: 'Checkout database pool saturation', secondary_root_causes: ['Inventory retry amplification'], confidence: 0.9, evidence_ids: [evidenceId], recommended_actions: ['Increase database pool headroom before the next load test.', 'Reduce inventory retry amplification.'], verification_status: 'passed' },
  report: null,
  stop_reason: 'completed',
}

const cost = {
  run_id: runId,
  status: 'completed',
  model: 'local-placeholder',
  model_execution_count: 5,
  failed_model_execution_count: 0,
  usage_breakdown_available: true,
  input_tokens: 0,
  output_tokens: 0,
  total_tokens: 0,
  provider_estimated_cost: 0,
  total_estimated_cost: 0,
  tool_call_count: 3,
  retrieval_depth: 20,
  model_latency: { count: 5, p50_ms: 18.4, p95_ms: 31.2 },
  tool_latency: { count: 3, p50_ms: 44.1, p95_ms: 52.8 },
  time_to_first_investigation_step_ms: 12.5,
  time_to_diagnosis_ms: 410.2,
  time_to_verified_resolution_ms: 680.4,
}

const dashboard = {
  run_count: 2,
  runs: [
    {
      evaluation_run_id: '11111111-1111-4111-8111-111111111111', dataset_version: 'opssentinel-benchmark-v1.0', architecture_version: 'explicit-planner-v1', model: 'local-placeholder', seed: 7,
      configuration: { evidence_mode: 'verification_enabled', stopping_strategy: 'confidence_threshold' }, created_at: '2026-09-08T14:00:00Z', prompt_version: 'prompt-v9', scenario_version: 'scenario-v1.0', evaluation_version: 'evaluation-v1.0', retrieval_settings: { depth: 20 }, tool_budget: 15, recorded_at: '2026-09-08T14:05:00Z', scenario_count: 10, linked_agent_run_count: 10,
      metrics: { correctness_mean: 0.9, confidence_mean: 0.82, primary_root_cause_accuracy_mean: 0.8, evidence_precision_mean: 0.76, evidence_recall_mean: 0.71, total_tool_calls_mean: 4.4, unsafe_action_attempts_total: 0 }, failure_categories: { evidence_miss: 1 },
    },
    {
      evaluation_run_id: '22222222-2222-4222-8222-222222222222', dataset_version: 'opssentinel-benchmark-v1.0', architecture_version: 'reactive-react-v1', model: 'local-placeholder', seed: 3,
      configuration: { evidence_mode: 'passive_only' }, created_at: '2026-09-08T13:00:00Z', prompt_version: 'prompt-v9', scenario_version: 'scenario-v1.0', evaluation_version: 'evaluation-v1.0', retrieval_settings: { depth: 10 }, tool_budget: 10, recorded_at: '2026-09-08T13:05:00Z', scenario_count: 10, linked_agent_run_count: 10,
      metrics: { correctness_mean: 0.8, confidence_mean: 0.79, primary_root_cause_accuracy_mean: 0.8, evidence_precision_mean: 0.7, evidence_recall_mean: 0.65, total_tool_calls_mean: 3.2, unsafe_action_attempts_total: 0 }, failure_categories: { overconfidence: 1 },
    },
  ],
}

const browser = await chromium.launch({ headless: true })
try {
  const incidentPage = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
  await incidentPage.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path === '/api/agent/runs' && request.method() === 'POST') {
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(run) })
      return
    }
    if (path.includes('/api/observability/runs/') && path.endsWith('/cost')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(cost) })
      return
    }
    if (path.includes('/api/agent/runs/') && request.method() === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(run) })
      return
    }
    await route.fulfill({ status: 404, contentType: 'application/json', body: '{"detail":"not mocked"}' })
  })
  await incidentPage.goto('http://127.0.0.1:5173/', { waitUntil: 'networkidle' })
  await incidentPage.getByTestId('start-investigation').click()
  await incidentPage.getByTestId('diagnosis-panel').waitFor()
  await incidentPage.getByTestId('measurement-panel').waitFor()
  await incidentPage.screenshot({ path: 'incident-console-light.png', fullPage: true })

  const dashboardPage = await browser.newPage({ viewport: { width: 1600, height: 1200 } })
  await dashboardPage.route('**/api/observability/experiments**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(dashboard) })
  })
  await dashboardPage.goto('http://127.0.0.1:5173/?experiments=1', { waitUntil: 'networkidle' })
  await dashboardPage.getByTestId('experiment-run-card').first().waitFor()
  await dashboardPage.screenshot({ path: 'experiment-dashboard-light.png', fullPage: true })
} finally {
  await browser.close()
}
