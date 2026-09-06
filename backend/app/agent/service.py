from __future__ import annotations

from uuid import UUID

from sqlalchemy import Engine

from app.agent.architectures import ReactivePhase5Runtime
from app.agent.models import (
    AgentBudget,
    AgentRunView,
    ApprovalDecisionRequest,
    StartInvestigationRequest,
)
from app.agent.phase5_runtime import Phase5Runtime
from app.agent.providers import (
    DeterministicReasoningProvider,
    OllamaReasoningProvider,
    ReasoningProvider,
)
from app.agent.resilience import DiminishingReturnsReasoningProvider
from app.agent.store import SqlAgentStore
from app.config import Settings, get_settings
from app.mcp.registry import ToolRegistry, build_registry
from app.mcp.retrying import RetryingToolRegistry
from app.persistence.session import create_database_engine


class AgentService:
    def __init__(
        self,
        *,
        settings: Settings,
        engine: Engine,
        registry: ToolRegistry,
        provider: ReasoningProvider,
    ) -> None:
        self.settings = settings
        self.provider: ReasoningProvider = DiminishingReturnsReasoningProvider(
            provider,
            max_non_progress_steps=settings.max_non_progress_steps,
        )
        resilient_registry = RetryingToolRegistry(
            registry,
            max_retries=settings.max_tool_retries,
            backoff_seconds=settings.tool_retry_backoff_seconds,
        )
        self.runtime_type: type[Phase5Runtime]
        if settings.agent_architecture == "reactive_react":
            self.runtime_type = ReactivePhase5Runtime
        else:
            self.runtime_type = Phase5Runtime
        self.store = SqlAgentStore(
            engine,
            architecture_version=self.runtime_type.architecture_version,
            model=self.provider.name,
        )
        self.runtime = self.runtime_type(
            registry=resilient_registry,
            provider=self.provider,
            store=self.store,
        )

    def default_budget(self) -> AgentBudget:
        return AgentBudget(
            max_steps=self.settings.max_steps,
            max_tool_calls=self.settings.max_tool_calls,
            max_repeated_identical_calls=self.settings.max_repeated_identical_calls,
            time_limit_seconds=self.settings.agent_time_limit_seconds,
            token_budget=self.settings.agent_token_budget,
            cost_budget=self.settings.agent_cost_budget,
        )

    async def start(self, request: StartInvestigationRequest) -> AgentRunView:
        runtime = self.runtime
        if request.pause_after is not None:
            runtime = self.runtime_type(
                registry=self.runtime.registry,
                provider=self.provider,
                store=self.store,
                interrupt_after=[request.pause_after],
            )
        state = await runtime.start(
            request.incident,
            request.budget or self.default_budget(),
            operational_mode=request.operational_mode,
        )
        return AgentRunView.from_state(state)

    async def resume(self, run_id: UUID) -> AgentRunView:
        state = await self.runtime.resume(run_id)
        return AgentRunView.from_state(state)

    async def decide_approval(
        self,
        run_id: UUID,
        request: ApprovalDecisionRequest,
    ) -> AgentRunView:
        state = await self.runtime.decide_approval(
            run_id,
            decision=request.decision,
            actor=request.actor,
        )
        return AgentRunView.from_state(state)

    def get(self, run_id: UUID) -> AgentRunView | None:
        state = self.store.load(run_id)
        return AgentRunView.from_state(state) if state is not None else None


def build_reasoning_provider(settings: Settings) -> ReasoningProvider:
    provider = settings.llm_provider.lower()
    if provider in {"deterministic", "test"}:
        return DeterministicReasoningProvider()
    if provider == "local" and settings.llm_model == "local-placeholder":
        return DeterministicReasoningProvider()
    if provider in {"local", "ollama"}:
        return OllamaReasoningProvider(
            base_url=settings.local_model_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    raise ValueError(
        "unsupported OPSSENTINEL_LLM_PROVIDER; use deterministic, local, or ollama"
    )


def build_agent_service(settings: Settings | None = None) -> AgentService:
    resolved = settings or get_settings()
    engine = create_database_engine(resolved)
    registry = build_registry(resolved)
    provider = build_reasoning_provider(resolved)
    return AgentService(
        settings=resolved,
        engine=engine,
        registry=registry,
        provider=provider,
    )
