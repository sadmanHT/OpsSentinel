from benchmarklab.catalog import load_catalog
from researchlab.benchmark_adapter import scenario_refs_from_benchmark
from researchlab.models import MAX_DATABASE_SEED, ExperimentKind, ExperimentSplit
from researchlab.plans import build_phase8_plans
from researchlab.runner import ExperimentRunner


def main() -> None:
    plans = build_phase8_plans()
    assert len(plans) == 6
    assert [plan.experiment for plan in plans] == list(ExperimentKind)
    assert [len(plan.cells) for plan in plans] == [2, 4, 4, 2, 2, 2]
    assert [cell.configuration.tool_budget for cell in plans[1].cells] == [5, 10, 15, 20]

    catalog = load_catalog()
    refs = scenario_refs_from_benchmark(catalog.scenarios)
    assert len(refs) == 50
    assert {ref.scenario_id for ref in refs} == {
        scenario.scenario_id for scenario in catalog.scenarios
    }
    expected_ref_fields = {"scenario_id", "scenario_version", "split", "difficulty"}
    assert all(set(ref.model_dump()) == expected_ref_fields for ref in refs)

    validation_refs = scenario_refs_from_benchmark(
        catalog.scenarios,
        split=ExperimentSplit.VALIDATION,
    )
    assert validation_refs
    planning = plans[0]
    trials = ExperimentRunner().enumerate_trials(planning, validation_refs)
    assert trials
    assert all(0 <= identity.seed <= MAX_DATABASE_SEED for identity, _, _ in trials)
    assert all(identity.dataset_version == planning.dataset_version for identity, _, _ in trials)
    print("Phase 8 ResearchLab plan/BenchmarkLab smoke passed")


if __name__ == "__main__":
    main()
