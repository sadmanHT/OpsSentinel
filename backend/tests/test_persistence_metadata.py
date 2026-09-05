from app.persistence.base import Base
from app.persistence import models  # noqa: F401


def test_phase_one_tables_are_registered() -> None:
    expected = {
        "incidents",
        "agent_runs",
        "evidence",
        "hypotheses",
        "tool_calls",
        "approvals",
        "diagnoses",
        "evaluation_runs",
        "evaluation_scores",
        "experiment_metadata",
    }
    assert expected == set(Base.metadata.tables)
