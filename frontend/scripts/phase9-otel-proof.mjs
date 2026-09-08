import { writeFile } from 'node:fs/promises'
import { chromium } from 'playwright'

const outputPath = process.env.OPSSENTINEL_OTEL_BROWSER_ARTIFACT ?? 'phase9-otel-browser.json'
const url = process.env.OPSSENTINEL_OTEL_BROWSER_URL ?? 'http://127.0.0.1:5173/?otel=1'

const browserErrors = []
const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage()
  page.on('pageerror', (error) => browserErrors.push(`pageerror: ${error.message}`))
  page.on('console', (message) => {
    if (message.type() === 'error') {
      browserErrors.push(`console: ${message.text()}`)
    }
  })

  await page.goto(url, { waitUntil: 'networkidle' })
  await page.getByTestId('trace-proof-run').click()
  await page.waitForFunction(() => {
    const status = document.querySelector('[data-testid="trace-proof-status"]')?.textContent ?? ''
    return status.includes('paused') || status.includes('error')
  }, undefined, { timeout: 45_000 })

  const statusText = (await page.getByTestId('trace-proof-status').textContent()) ?? ''
  const traceText = (await page.getByTestId('trace-id').textContent()) ?? ''
  const runText = (await page.getByTestId('run-id').textContent()) ?? ''
  const traceId = traceText.replace(/^Trace ID:\s*/, '').trim()
  const runId = runText.replace(/^Run ID:\s*/, '').trim()
  const status = statusText.replace(/^Status:\s*/, '').trim()
  const windowTraceId = await page.evaluate(() => window.__OPSSENTINEL_TRACE_ID__ ?? null)

  if (status !== 'paused') {
    throw new Error(`expected paused proof run, observed ${status || 'unknown'}`)
  }
  if (!/^[0-9a-f]{32}$/.test(traceId)) {
    throw new Error(`invalid trace id ${traceId}`)
  }
  if (!/^[0-9a-f-]{36}$/.test(runId)) {
    throw new Error(`invalid run id ${runId}`)
  }
  if (windowTraceId !== traceId) {
    throw new Error('visible trace id does not match the browser tracing runtime')
  }
  if (browserErrors.length > 0) {
    throw new Error(`browser emitted errors: ${browserErrors.join('; ')}`)
  }

  await writeFile(
    outputPath,
    `${JSON.stringify(
      {
        trace_id: traceId,
        run_id: runId,
        status,
        browser_url: url,
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
