import {
  ROOT_CONTEXT,
  SpanKind,
  SpanStatusCode,
  propagation,
  trace,
  type TextMapSetter,
  type Tracer,
} from '@opentelemetry/api'
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base'
import { WebTracerProvider } from '@opentelemetry/sdk-trace-web'

const TRACE_QUERY_FLAG = 'otel'
const TRACE_SERVICE_NAME = 'opssentinel-frontend'
const TRACE_SCOPE_NAME = 'opssentinel.browser'

const headerSetter: TextMapSetter<Headers> = {
  set(carrier, key, value) {
    carrier.set(key, value)
  },
}

type BrowserTracingRuntime = {
  provider: WebTracerProvider
  tracer: Tracer
}

type AgentRunResponse = {
  run_id?: string
  status?: string
}

export type TracedInvestigationResult = {
  traceId: string | null
  runId: string | null
  status: string | null
}

let tracingRuntime: BrowserTracingRuntime | null = null

export function browserTracingEnabled(search = window.location.search): boolean {
  return new URLSearchParams(search).get(TRACE_QUERY_FLAG) === '1'
}

function collectorTraceEndpoint(): string {
  return `${window.location.protocol}//${window.location.hostname}:4318/v1/traces`
}

function initializeBrowserTracing(): BrowserTracingRuntime | null {
  if (!browserTracingEnabled()) {
    return null
  }
  if (tracingRuntime) {
    return tracingRuntime
  }

  const exporter = new OTLPTraceExporter({ url: collectorTraceEndpoint() })
  const provider = new WebTracerProvider({
    resource: resourceFromAttributes({
      'service.name': TRACE_SERVICE_NAME,
      'deployment.environment.name': 'development',
    }),
    spanProcessors: [new SimpleSpanProcessor(exporter)],
  })
  provider.register()

  tracingRuntime = {
    provider,
    tracer: provider.getTracer(TRACE_SCOPE_NAME, '0.1.0'),
  }
  return tracingRuntime
}

function rememberTraceId(traceId: string): void {
  const traceWindow = window as typeof window & { __OPSSENTINEL_TRACE_ID__?: string }
  traceWindow.__OPSSENTINEL_TRACE_ID__ = traceId
}

export async function startInvestigation(payload: unknown): Promise<TracedInvestigationResult> {
  const runtime = initializeBrowserTracing()
  const headers = new Headers({ 'content-type': 'application/json' })

  if (!runtime) {
    const response = await fetch('/api/agent/runs', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    })
    if (!response.ok) {
      throw new Error(`agent request failed with status ${response.status}`)
    }
    const body = (await response.json()) as AgentRunResponse
    return {
      traceId: null,
      runId: body.run_id ?? null,
      status: body.status ?? null,
    }
  }

  const span = runtime.tracer.startSpan(
    'frontend.start_investigation',
    {
      kind: SpanKind.CLIENT,
      attributes: {
        'http.request.method': 'POST',
        'server.address': 'opssentinel-backend',
        'opssentinel.browser.trace_proof': true,
      },
    },
    ROOT_CONTEXT,
  )
  const traceId = span.spanContext().traceId
  rememberTraceId(traceId)
  propagation.inject(trace.setSpan(ROOT_CONTEXT, span), headers, headerSetter)

  try {
    const response = await fetch('/api/agent/runs', {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    })
    span.setAttribute('http.response.status_code', response.status)
    if (!response.ok) {
      span.setStatus({ code: SpanStatusCode.ERROR })
      throw new Error(`agent request failed with status ${response.status}`)
    }
    const body = (await response.json()) as AgentRunResponse
    span.setStatus({ code: SpanStatusCode.OK })
    return {
      traceId,
      runId: body.run_id ?? null,
      status: body.status ?? null,
    }
  } catch (error) {
    const failure = error instanceof Error ? error : new Error(String(error))
    span.recordException(failure)
    span.setStatus({ code: SpanStatusCode.ERROR, message: failure.message })
    throw failure
  } finally {
    span.end()
    await runtime.provider.forceFlush()
  }
}
