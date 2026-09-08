export type ExperimentMetrics = {
  correctness_mean: number | null
  confidence_mean: number | null
  primary_root_cause_accuracy_mean: number | null
  evidence_precision_mean: number | null
  evidence_recall_mean: number | null
  total_tool_calls_mean: number | null
  unsafe_action_attempts_total: number | null
}

export type ExperimentRunSummary = {
  evaluation_run_id: string
  dataset_version: string
  architecture_version: string
  model: string
  seed: number
  configuration: Record<string, unknown>
  created_at: string
  prompt_version: string | null
  scenario_version: string | null
  evaluation_version: string | null
  retrieval_settings: Record<string, unknown>
  tool_budget: number | null
  recorded_at: string | null
  scenario_count: number
  linked_agent_run_count: number
  metrics: ExperimentMetrics
  failure_categories: Record<string, number>
}

export type ExperimentDashboardResponse = {
  run_count: number
  runs: ExperimentRunSummary[]
}

export async function getExperimentDashboard(limit = 20): Promise<ExperimentDashboardResponse> {
  const response = await fetch(`/api/observability/experiments?limit=${encodeURIComponent(limit)}`)
  if (!response.ok) {
    let detail = `request failed with status ${response.status}`
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // Keep the status-based fallback when the response is not JSON.
    }
    throw new Error(detail)
  }
  return (await response.json()) as ExperimentDashboardResponse
}
