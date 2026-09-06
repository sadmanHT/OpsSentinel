from __future__ import annotations

from researchlab.models import (
    ArchitectureVariant,
    Difficulty,
    EvidenceMode,
    ExperimentCell,
    ExperimentKind,
    ExperimentPlan,
    ExperimentSplit,
    ResearchConfiguration,
    StoppingStrategy,
    TemporalReasoningVariant,
    ToolOrderVariant,
)

ALL_DIFFICULTIES = [
    Difficulty.EASY,
    Difficulty.MEDIUM,
    Difficulty.HARD,
    Difficulty.ADVERSARIAL,
    Difficulty.COMPOUND,
]


def _cell(
    cell_id: str,
    label: str,
    configuration: ResearchConfiguration,
    difficulties: list[Difficulty] | None = None,
) -> ExperimentCell:
    return ExperimentCell(
        id=cell_id,
        label=label,
        configuration=configuration,
        difficulties=list(difficulties or ALL_DIFFICULTIES),
    )


def build_phase8_plans(
    *,
    dataset_version: str = "ops-v1",
    split: ExperimentSplit = ExperimentSplit.VALIDATION,
    provider: str = "local",
    model: str = "local-placeholder",
    prompt_version: str = "phase8-v1",
    repeat_count: int = 1,
) -> list[ExperimentPlan]:
    baseline = ResearchConfiguration(
        provider=provider,
        model=model,
        prompt_version=prompt_version,
    )

    planning = ExperimentPlan(
        id="phase8-planning-difficulty",
        experiment=ExperimentKind.PLANNING_DIFFICULTY,
        hypothesis_id="H1",
        dataset_version=dataset_version,
        split=split,
        repeat_count=repeat_count,
        seed_base=8100,
        cells=[
            _cell(
                "reactive",
                "Reactive ReAct",
                baseline.model_copy(update={"architecture": ArchitectureVariant.REACTIVE_REACT}),
            ),
            _cell(
                "planner",
                "Explicit planner",
                baseline.model_copy(update={"architecture": ArchitectureVariant.EXPLICIT_PLANNER}),
            ),
        ],
    )

    budget = ExperimentPlan(
        id="phase8-investigation-budget",
        experiment=ExperimentKind.INVESTIGATION_BUDGET,
        hypothesis_id="H2",
        dataset_version=dataset_version,
        split=split,
        repeat_count=repeat_count,
        seed_base=8200,
        cells=[
            _cell(
                f"budget-{value}",
                f"{value} tool calls",
                baseline.model_copy(update={"tool_budget": value}),
            )
            for value in (5, 10, 15, 20)
        ],
    )

    tool_order = ExperimentPlan(
        id="phase8-tool-order",
        experiment=ExperimentKind.TOOL_ORDER,
        hypothesis_id="H2",
        dataset_version=dataset_version,
        split=split,
        repeat_count=repeat_count,
        seed_base=8300,
        cells=[
            _cell(
                variant.value.replace("_", "-"),
                label,
                baseline.model_copy(update={"tool_order": variant}),
            )
            for variant, label in (
                (ToolOrderVariant.FREE, "Reactive free choice"),
                (ToolOrderVariant.DEPLOYMENT_FIRST, "Deployment-first"),
                (ToolOrderVariant.SYMPTOM_FIRST, "Symptom-first"),
                (ToolOrderVariant.ADAPTIVE, "Adaptive order"),
            )
        ],
    )

    verification = ExperimentPlan(
        id="phase8-passive-verification",
        experiment=ExperimentKind.PASSIVE_VS_VERIFICATION,
        hypothesis_id="H4",
        dataset_version=dataset_version,
        split=split,
        repeat_count=repeat_count,
        seed_base=8400,
        cells=[
            _cell(
                "passive-only",
                "Passive evidence only",
                baseline.model_copy(update={"evidence_mode": EvidenceMode.PASSIVE_ONLY}),
            ),
            _cell(
                "verification-enabled",
                "Passive evidence plus verification",
                baseline.model_copy(update={"evidence_mode": EvidenceMode.VERIFICATION_ENABLED}),
            ),
        ],
    )

    temporal = ExperimentPlan(
        id="phase8-temporal-reasoning",
        experiment=ExperimentKind.TEMPORAL_REASONING,
        hypothesis_id="H3",
        dataset_version=dataset_version,
        split=split,
        repeat_count=repeat_count,
        seed_base=8500,
        cells=[
            _cell(
                "standard",
                "Standard hypothesis representation",
                baseline.model_copy(
                    update={"temporal_reasoning": TemporalReasoningVariant.STANDARD}
                ),
            ),
            _cell(
                "explicit-cause-effect",
                "Explicit cause-time/effect-time validation",
                baseline.model_copy(
                    update={
                        "temporal_reasoning": TemporalReasoningVariant.EXPLICIT_CAUSE_EFFECT
                    }
                ),
            ),
        ],
    )

    compound = ExperimentPlan(
        id="phase8-compound-handling",
        experiment=ExperimentKind.COMPOUND_HANDLING,
        hypothesis_id="H5",
        dataset_version=dataset_version,
        split=split,
        repeat_count=repeat_count,
        seed_base=8600,
        cells=[
            _cell(
                "standard-stopping",
                "Standard confidence-threshold stopping",
                baseline.model_copy(
                    update={"stopping_strategy": StoppingStrategy.CONFIDENCE_THRESHOLD}
                ),
                [Difficulty.COMPOUND],
            ),
            _cell(
                "unresolved-evidence",
                "Require explanation of significant unresolved evidence",
                baseline.model_copy(
                    update={"stopping_strategy": StoppingStrategy.UNRESOLVED_EVIDENCE}
                ),
                [Difficulty.COMPOUND],
            ),
        ],
    )

    return [planning, budget, tool_order, verification, temporal, compound]
