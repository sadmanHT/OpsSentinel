import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text

from app.config import Settings
from app.persistence.session import create_database_engine


@pytest.mark.integration
def test_database_has_phase_one_tables_after_migration() -> None:
    settings = Settings(_env_file=None, database_url=os.environ["OPSSENTINEL_DATABASE_URL"])
    engine = create_database_engine(settings)
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
    assert expected.issubset(set(inspect(engine).get_table_names()))


@pytest.mark.integration
def test_incident_round_trip() -> None:
    settings = Settings(_env_file=None, database_url=os.environ["OPSSENTINEL_DATABASE_URL"])
    engine = create_database_engine(settings)
    incident_id = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO incidents
                    (id, title, description, severity, service, start_time, status)
                VALUES
                    (:id, 'test', 'round trip', 'P2', 'checkout', CURRENT_TIMESTAMP, 'open')
                """
            ),
            {"id": incident_id},
        )
        value = connection.execute(
            text("SELECT title FROM incidents WHERE id = :id"), {"id": incident_id}
        ).scalar_one()
    assert value == "test"
