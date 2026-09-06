from researchlab.models import ExperimentKind
from researchlab.plans import build_phase8_plans


def main() -> None:
    plans = build_phase8_plans()
    assert len(plans) == 6
    assert [plan.experiment for plan in plans] == list(ExperimentKind)
    assert [len(plan.cells) for plan in plans] == [2, 4, 4, 2, 2, 2]
    assert [cell.configuration.tool_budget for cell in plans[1].cells] == [5, 10, 15, 20]
    print("Phase 8 ResearchLab plan smoke passed")


if __name__ == "__main__":
    main()
