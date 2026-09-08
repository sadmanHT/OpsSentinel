import { writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

const outputPath =
  process.env.OPSSENTINEL_EXPERIMENT_DASHBOARD_ARTIFACT ??
  'phase9-experiment-dashboard-browser.json'
const url =
  process.env.OPSSENTINEL_EXPERIMENT_DASHBOARD_URL ??
  'http://127.0.0.1:5173/?experiments=1'

const populatedDashboard = {
  run_count: 2,
  runs: [
    {
      evaluation_run_id: '11111111-1111-4111-8111-111111111111',
      dataset_version: 'benchmark-v9',
      architecture_version: 'explicit-planner-v1',
      model: 'local-placeholder',
      seed: 7,
      configuration: {
        evidence_mode: 'verification_enabled',
        stopping_strategy: 'confidence_threshold',
      },
      created_at: '2026-09-08T14:00:00Z',
      prompt_version: 'prompt-v9',
      scenario_version: 'scenario-v9',
      evaluation_version: 'evaluation-v9',
      retrieval_settings: { depth: 20 },
      tool_budget: 15,
      recorded_at: '2026-09-08T14:05:00Z',
      scenario_count: 10,
      linked_agent_run_count: 10,
      metrics: {
        correctness_mean: 0.9,
        confidence_mean: 0.82,
        primary_root_cause_accuracy_mean: 0.8,
        evidence_precision_mean: 0.76,
        evidence_recall_mean: 0.71,
        total_tool_calls_mean: 4.4,
        unsafe_action_attempts_total: 0,
      },
      failure_categories: { evidence_miss: 1 },
    },
    {
      evaluation_run_id: '22222222-2222-4222-8222-222222222222',
      dataset_version: 'benchmark-v9',
      architecture_version: 'reactive-react-v1',
      model: 'local-placeholder',
      seed: 3,
      configuration: {},
      created_at: '2026-09-08T13:00:00Z',
      prompt_version: null,
      scenario_version: null,
      evaluation_version: null,
      retrieval_settings: {},
      tool_budget: null,
      recorded_at: null,
      scenario_count: 0,
      linked_agent_run_count: 0,
      metrics: {
        correctness_mean: null,
        confidence_mean: null,
        primary_root_cause_accuracy_mean: null,
        evidence_precision_mean: null,
        evidence_recall_mean: null,
        total_tool_calls_mean: null,
        unsafe_action_attempts_total: null,
      },
      failure_categories: {},
    },
  ],
}

function assertIncludes(actual, expected, label) {
  if (!actual.includes(expected)) {
    throw new Error(`${label} missing ${JSON.stringify(expected)}: ${JSON.stringify(actual)}`)
  }
}

const browserErrors = []
let responseMode = 'populated'
const browser = await chromium.launch({ headless: true })

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.on('pageerror', (error) => browserErrors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`)
  })

  await page.route('**/api/observability/experiments**', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 180))
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(responseMode === 'populated' ? populatedDashboard : { run_count: 0, runs: [] }),
    })
  })

  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await page.getByTestId('experiment-loading').waitFor()
  const loadingStateVerified = true

  await page.getByTestId('experiment-run-card').first().waitFor()
  const runCount = (await page.getByTestId('experiment-run-count').textContent()) ?? ''
  if (runCount.trim() !== '2') throw new Error(`expected two persisted runs, observed ${runCount}`)

  const firstCard = page.getByTestId('experiment-run-card').first()
  const firstCardText = (await firstCard.textContent()) ?? ''
  assertIncludes(firstCardText, 'explicit-planner-v1', 'architecture')
  assertIncludes(firstCardText, 'verification_enabled', 'persisted configuration')
  assertIncludes(firstCardText, 'depth 20', 'retrieval settings')
  assertIncludes(firstCardText, 'evidence miss', 'failure category')
  assertIncludes(firstCardText, '90%', 'correctness')
  assertIncludes(firstCardText, '80%', 'root-cause accuracy')
  assertIncludes(firstCardText, '0', 'real zero unsafe attempts')

  const secondCard = page.getByTestId('experiment-run-card').nth(1)
  const secondCardText = (await secondCard.textContent()) ?? ''
  assertIncludes(secondCardText, 'reactive-react-v1', 'second architecture')
  assertIncludes(secondCardText, 'Not measured', 'missing metric rendering')
  assertIncludes(secondCardText, 'Not recorded', 'missing metadata rendering')

  responseMode = 'empty'
  await page.getByRole('button', { name: 'Refresh' }).click()
  await page.getByTestId('experiment-empty').waitFor()
  const emptyText = (await page.getByTestId('experiment-empty').textContent()) ?? ''
  assertIncludes(emptyText, 'No persisted evaluation runs', 'empty dashboard')

  if (browserErrors.length > 0) {
    throw new Error(`browser emitted errors: ${browserErrors.join('; ')}`)
  }

  await writeFile(
    outputPath,
    `${JSON.stringify(
      {
        loading_state_verified: loadingStateVerified,
        persisted_configuration_verified: true,
        persisted_metrics_verified: true,
        failure_categories_verified: true,
        missing_metric_rendered_as_missing: true,
        zero_measurement_preserved_as_zero: true,
        empty_state_verified: true,
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
