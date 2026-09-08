import { readFile, writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

const inputPath = process.env.OPSSENTINEL_FRONTEND_SCENARIO_INPUT
const outputPath = process.env.OPSSENTINEL_FRONTEND_SCENARIO_OUTPUT
const url = process.env.OPSSENTINEL_FRONTEND_URL ?? 'http://127.0.0.1:5173/'

if (!inputPath || !outputPath) {
  throw new Error('scenario input and output paths are required')
}

const incident = JSON.parse(await readFile(inputPath, 'utf8'))
const expectedInputKeys = ['description', 'service', 'severity', 'title']
if (JSON.stringify(Object.keys(incident).sort()) !== JSON.stringify(expectedInputKeys)) {
  throw new Error(`unexpected browser input keys: ${JSON.stringify(Object.keys(incident).sort())}`)
}

const browserErrors = []
let observedRequest = null
const browser = await chromium.launch({ headless: true })

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  page.setDefaultTimeout(180_000)
  page.on('pageerror', (error) => browserErrors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(`console: ${message.text()}`)
  })
  page.on('request', (request) => {
    const parsed = new URL(request.url())
    if (parsed.pathname === '/api/agent/runs' && request.method() === 'POST') {
      observedRequest = request.postDataJSON()
    }
  })

  await page.goto(url, { waitUntil: 'networkidle' })
  await page.getByTestId('incident-console').waitFor()
  await page.getByLabel('Incident title').fill(incident.title)
  await page.getByLabel('Service').fill(incident.service)
  await page.getByLabel('Severity').selectOption(incident.severity)
  await page.getByLabel('Observable symptoms').fill(incident.description)

  const operationalToggle = page.getByLabel('Operational mode')
  if (await operationalToggle.isChecked()) {
    throw new Error('representative frontend run unexpectedly enabled operational mode')
  }

  const responsePromise = page.waitForResponse(
    (response) => {
      const parsed = new URL(response.url())
      return parsed.pathname === '/api/agent/runs' && response.request().method() === 'POST'
    },
    { timeout: 180_000 },
  )
  await page.getByTestId('start-investigation').click()
  const response = await responsePromise
  if (response.status() !== 201) {
    throw new Error(
      `agent launch returned HTTP ${response.status()}: ${(await response.text()).slice(0, 500)}`,
    )
  }
  const initialRun = await response.json()

  if (!observedRequest || typeof observedRequest !== 'object') {
    throw new Error('browser did not observe the agent launch request body')
  }
  const rootKeys = Object.keys(observedRequest).sort()
  const incidentKeys = Object.keys(observedRequest.incident ?? {}).sort()
  const expectedRootKeys = ['incident', 'operational_mode']
  const expectedIncidentKeys = [
    'description',
    'service',
    'severity',
    'start_time',
    'status',
    'title',
  ]
  if (JSON.stringify(rootKeys) !== JSON.stringify(expectedRootKeys)) {
    throw new Error(`unexpected agent request root keys: ${JSON.stringify(rootKeys)}`)
  }
  if (JSON.stringify(incidentKeys) !== JSON.stringify(expectedIncidentKeys)) {
    throw new Error(`unexpected agent incident keys: ${JSON.stringify(incidentKeys)}`)
  }
  if (observedRequest.operational_mode !== false) {
    throw new Error('representative frontend request must be non-operational')
  }
  if ('scenario_id' in observedRequest.incident) {
    throw new Error('scenario_id leaked into the frontend agent request')
  }

  await page.getByTestId('run-status').waitFor()
  await page.waitForFunction(() => {
    const text = document.querySelector('[data-testid="run-status"]')?.textContent?.trim()
    return text === 'completed' || text === 'budget exhausted' || text === 'failed'
  })

  const terminalStatus = ((await page.getByTestId('run-status').textContent()) ?? '').trim()
  const timelineRendered = await page.getByTestId('investigation-timeline').isVisible()
  const evidenceRendered = await page.getByTestId('evidence-panel').isVisible()
  const hypothesesRendered = await page.getByTestId('hypotheses-panel').isVisible()
  const completedRendered = await page.getByTestId('completed-state').isVisible().catch(() => false)
  const failureRendered = await page.getByTestId('agent-failure-state').isVisible().catch(() => false)

  if (!timelineRendered || !evidenceRendered || !hypothesesRendered) {
    throw new Error('representative run did not render the investigation workspace')
  }
  if (terminalStatus === 'completed' && !completedRendered) {
    throw new Error('completed run did not render the completed state')
  }
  if ((terminalStatus === 'budget exhausted' || terminalStatus === 'failed') && !failureRendered) {
    throw new Error('non-completed terminal run did not render the failure state')
  }
  if (browserErrors.length > 0) {
    throw new Error(`browser emitted errors: ${browserErrors.join('; ')}`)
  }

  await writeFile(
    outputPath,
    `${JSON.stringify(
      {
        run_id: initialRun.run_id,
        initial_status: initialRun.status,
        terminal_status_label: terminalStatus,
        request_shape_safe: true,
        scenario_id_absent_from_request: true,
        operational_mode_disabled: true,
        timeline_rendered: timelineRendered,
        evidence_panel_rendered: evidenceRendered,
        hypotheses_panel_rendered: hypothesesRendered,
        terminal_state_rendered: completedRendered || failureRendered,
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
