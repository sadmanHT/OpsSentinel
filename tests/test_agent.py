import unittest

from src.opssentinel.agent import AutonomousSREAgent


class AutonomousSREAgentTests(unittest.TestCase):
    def test_collects_all_investigation_sources(self) -> None:
        calls = []

        def make_reader(name, value):
            def _reader(_incident_id):
                calls.append(name)
                return value

            return _reader

        agent = AutonomousSREAgent(
            logs_reader=make_reader("logs", ["ERROR timeout"]),
            metrics_reader=make_reader("metrics", {"error_rate": 0.10}),
            database_reader=make_reader("database", {"failing": False}),
            deployments_reader=make_reader("deployments", [{"recent": True}]),
            code_changes_reader=make_reader("code", ["timeout value updated"]),
            docs_reader=make_reader("docs", {"runbook_mismatch": False}),
        )

        report = agent.investigate("INC-100")

        self.assertEqual(
            set(calls), {"logs", "metrics", "database", "deployments", "code", "docs"}
        )
        self.assertEqual(
            set(report.evidence.keys()),
            {
                "application_logs",
                "infrastructure_metrics",
                "database_health",
                "deployment_history",
                "source_code_changes",
                "operational_documentation",
            },
        )

    def test_identifies_root_cause_and_proposes_remediation(self) -> None:
        agent = AutonomousSREAgent(
            logs_reader=lambda _: ["ERROR: request timeout spike"],
            metrics_reader=lambda _: {"error_rate": 0.21},
            database_reader=lambda _: {"failing": False},
            deployments_reader=lambda _: [{"version": "1.2.3", "recent": True}],
            code_changes_reader=lambda _: ["timeout config changed"],
            docs_reader=lambda _: {"runbook_mismatch": False},
        )

        report = agent.investigate("INC-200")

        self.assertIn("deployment", report.root_cause.lower())
        self.assertTrue(any("rollback" in step.lower() for step in report.remediation))

    def test_verifies_recovery_from_post_remediation_evidence(self) -> None:
        agent = AutonomousSREAgent(
            logs_reader=lambda _: ["ERROR: initial outage signal"],
            metrics_reader=lambda _: {"error_rate": 0.30},
            database_reader=lambda _: {"failing": True},
            deployments_reader=lambda _: [{"recent": True}],
            code_changes_reader=lambda _: ["migration updated connection timeout"],
            docs_reader=lambda _: {"runbook_mismatch": False},
        )

        recovered_evidence = {
            "application_logs": ["INFO: service healthy"],
            "infrastructure_metrics": {"error_rate": 0.005},
            "database_health": {"failing": False},
        }

        report = agent.investigate(
            "INC-300", post_remediation_evidence=recovered_evidence
        )

        self.assertTrue(report.recovery_verified)
        self.assertIn("recovery verified", report.recovery_notes.lower())


if __name__ == "__main__":
    unittest.main()
