export type AgentRunStatus =
  | 'created'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'budget_exhausted'

export type ApprovalDecision = 'pending' | 'approved' | 'rejected' | 'abandoned'
export type VerificationStatus = 'not_run' | 'passed' | 'failed' | 'inconclusive'

export type Incident = {
  id: string
  title: string
  description: string
  severity: 'P0' | 'P1' | 'P2' | 'P3' | 'P4'
  service: string
  start_time: string
  status: 'open' | 'investigating' | 'mitigated' | 'resolved' | 'closed'
  scenario_id: string | null
}

export type Evidence = {
  id: string
  incident_id: string
  source: string
  evidence_type:
    | 'log'
    | 'metric'
    | 'database'
    | 'code'
    | 'deployment'
    | 'documentation'
    | 'diagnostic'
    | 'verification'
  service: string | null
  timestamp: string
  observation: string
  raw_reference: string | null
  reliability: number
}

export type Hypothesis = {
  id: string
  description: string
  root_cause_code: string
  confidence: number
  supporting_evidence: string[]
  contradicting_evidence: string[]
  first_possible_cause_time: string | null
  effect_time: string | null
  status: 'active' | 'rejected' | 'confirmed'
}

export type ToolCall = {
  id: string
  tool_name: string
  arguments: Record<string, unknown>
  started_at: string
  completed_at: string | null
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'blocked'
  result_reference: string | null
  risk_level: 'R0' | 'R1' | 'R2' | 'R3'
}

export type PlanStep = {
  id: string
  objective: string
  tool: string
  arguments: Record<string, unknown>
  rationale: string
  required: boolean
  completed: boolean
}

export type InvestigationPlan = {
  summary: string
  steps: PlanStep[]
}

export type AgentBudget = {
  max_steps: number
  max_tool_calls: number
  max_repeated_identical_calls: number
  time_limit_seconds: number
  token_budget: number
  cost_budget: number
  steps_used: number
  tool_calls_used: number
  tokens_used: number
  cost_used: number
  repeated_calls: Record<string, number>
  exhausted_reason: string | null
}

export type ProposedAction = {
  description: string
  risk_level: 'R0' | 'R1' | 'R2' | 'R3'
  rationale: string
  evidence_ids: string[]
  tool: string | null
  arguments: Record<string, unknown>
  expected_benefit: string
  possible_risk: string
  rollback_strategy: string
}

export type ApprovalRequest = {
  id: string
  action: ProposedAction
  why_proposed: string
  evidence_ids: string[]
  expected_benefit: string
  possible_risk: string
  rollback_strategy: string
  decision: ApprovalDecision
  created_at: string
  decided_at: string | null
  decided_by: string | null
}

export type VerificationResult = {
  status: VerificationStatus
  summary: string
  evidence_ids: string[]
}

export type Diagnosis = {
  primary_root_cause: string
  secondary_root_causes: string[]
  confidence: number
  evidence_ids: string[]
  recommended_actions: string[]
  verification_status: VerificationStatus
}

export type GroundedClaim = {
  statement: string
  evidence_ids: string[]
}

export type AgentReport = {
  run_id: string
  status: AgentRunStatus
  root_cause_code: string
  diagnosis: Diagnosis
  claims: GroundedClaim[]
  proposed_action: ProposedAction | null
  verification: VerificationResult
  generated_at: string
}

export type ToolFailureRecord = {
  tool: string
  code: string
  message: string
  retryable: boolean
  attempt: number
  recorded_at: string
}

export type AgentRunView = {
  run_id: string
  incident: Incident
  status: AgentRunStatus
  next_node: string
  operational_mode: boolean
  operation_stage: string
  plan: InvestigationPlan | null
  evidence: Evidence[]
  hypotheses: Hypothesis[]
  tool_history: ToolCall[]
  confidence: number
  budget: AgentBudget
  proposed_action: ProposedAction | null
  approval: ApprovalRequest | null
  verification: VerificationResult
  failures: ToolFailureRecord[]
  diagnosis_code: string | null
  final_diagnosis: Diagnosis | null
  report: AgentReport | null
  stop_reason: string | null
}

export type StartInvestigationPayload = {
  incident: {
    title: string
    description: string
    severity: Incident['severity']
    service: string
    start_time: string
    status: Incident['status']
  }
  operational_mode: boolean
}

export type LatencyDistribution = {
  count: number
  p50_ms: number | null
  p95_ms: number | null
}

export type RunCostSummary = {
  run_id: string
  status: string
  model: string
  model_execution_count: number
  failed_model_execution_count: number
  usage_breakdown_available: boolean
  input_tokens: number
  output_tokens: number
  total_tokens: number
  provider_estimated_cost: number
  total_estimated_cost: number
  tool_call_count: number
  retrieval_depth: number
  model_latency: LatencyDistribution
  tool_latency: LatencyDistribution
  time_to_first_investigation_step_ms: number | null
  time_to_diagnosis_ms: number | null
  time_to_verified_resolution_ms: number | null
}

class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    let detail = `request failed with status ${response.status}`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // Keep the status-based fallback when the response is not JSON.
    }
    throw new ApiError(detail, response.status)
  }
  return (await response.json()) as T
}

function jsonInit(method: 'POST', body?: unknown): RequestInit {
  return {
    method,
    headers: { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

export function startInvestigation(payload: StartInvestigationPayload): Promise<AgentRunView> {
  return requestJson<AgentRunView>('/api/agent/runs', jsonInit('POST', payload))
}

export function getInvestigation(runId: string): Promise<AgentRunView> {
  return requestJson<AgentRunView>(`/api/agent/runs/${encodeURIComponent(runId)}`)
}

export function resumeInvestigation(runId: string): Promise<AgentRunView> {
  return requestJson<AgentRunView>(
    `/api/agent/runs/${encodeURIComponent(runId)}/resume`,
    jsonInit('POST'),
  )
}

export function decideApproval(
  runId: string,
  decision: Exclude<ApprovalDecision, 'pending'>,
  actor: string,
): Promise<AgentRunView> {
  return requestJson<AgentRunView>(
    `/api/agent/runs/${encodeURIComponent(runId)}/approval`,
    jsonInit('POST', { decision, actor }),
  )
}

export async function getRunCostSummary(runId: string): Promise<RunCostSummary | null> {
  try {
    return await requestJson<RunCostSummary>(
      `/api/observability/runs/${encodeURIComponent(runId)}/cost`,
    )
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}
