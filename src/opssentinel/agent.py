from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


SourceReader = Callable[[str], Any]


@dataclass
class InvestigationReport:
    incident_id: str
    evidence: Dict[str, Any]
    root_cause: str
    remediation: List[str]
    recovery_verified: bool
    recovery_notes: str


class AutonomousSREAgent:
    def __init__(
        self,
        logs_reader: SourceReader,
        metrics_reader: SourceReader,
        database_reader: SourceReader,
        deployments_reader: SourceReader,
        code_changes_reader: SourceReader,
        docs_reader: SourceReader,
    ) -> None:
        self._readers = {
            "application_logs": logs_reader,
            "infrastructure_metrics": metrics_reader,
            "database_health": database_reader,
            "deployment_history": deployments_reader,
            "source_code_changes": code_changes_reader,
            "operational_documentation": docs_reader,
        }

    def investigate(
        self, incident_id: str, post_remediation_evidence: Optional[Dict[str, Any]] = None
    ) -> InvestigationReport:
        evidence = self.collect_evidence(incident_id)
        root_cause = self.identify_root_cause(evidence)
        remediation = self.propose_remediation(root_cause)
        recovery_verified, recovery_notes = self.verify_recovery(
            post_remediation_evidence or evidence
        )
        return InvestigationReport(
            incident_id=incident_id,
            evidence=evidence,
            root_cause=root_cause,
            remediation=remediation,
            recovery_verified=recovery_verified,
            recovery_notes=recovery_notes,
        )

    def collect_evidence(self, incident_id: str) -> Dict[str, Any]:
        return {name: reader(incident_id) for name, reader in self._readers.items()}

    def identify_root_cause(self, evidence: Dict[str, Any]) -> str:
        metrics = evidence.get("infrastructure_metrics", {})
        logs = evidence.get("application_logs", [])
        database = evidence.get("database_health", {})
        deployments = evidence.get("deployment_history", [])
        code_changes = evidence.get("source_code_changes", [])
        docs = evidence.get("operational_documentation", {})

        error_rate = float(metrics.get("error_rate", 0))
        has_recent_deploy = bool(deployments and deployments[-1].get("recent", False))
        has_error_logs = any("error" in str(line).lower() for line in logs)
        db_failing = bool(database.get("failing", False))
        risky_change = any(
            key in str(change).lower()
            for change in code_changes
            for key in ("rollback", "migration", "timeout", "connection", "config")
        )
        runbook_mismatch = bool(docs.get("runbook_mismatch", False))

        if has_recent_deploy and error_rate >= 0.05 and has_error_logs:
            return "Recent deployment introduced a production regression."
        if db_failing and error_rate >= 0.02:
            return "Database instability is driving the incident."
        if risky_change and runbook_mismatch:
            return "Uncoordinated code and runbook change caused operational drift."
        return "Root cause is inconclusive; more evidence is required."

    def propose_remediation(self, root_cause: str) -> List[str]:
        root_lower = root_cause.lower()
        if "deployment" in root_lower:
            return [
                "Rollback to the previous stable release.",
                "Disable problematic feature flags.",
                "Run smoke tests and monitor error-rate SLOs.",
            ]
        if "database" in root_lower:
            return [
                "Fail over to healthy database replica.",
                "Restart degraded database nodes.",
                "Run data consistency and latency checks.",
            ]
        if "drift" in root_lower:
            return [
                "Align runbook and deployment configuration.",
                "Re-apply validated infrastructure settings.",
                "Re-run canary and operational readiness checks.",
            ]
        return [
            "Escalate to on-call engineering leads.",
            "Increase telemetry and gather additional diagnostics.",
        ]

    def verify_recovery(self, post_evidence: Dict[str, Any]) -> tuple[bool, str]:
        metrics = post_evidence.get("infrastructure_metrics", {})
        logs = post_evidence.get("application_logs", [])
        database = post_evidence.get("database_health", {})

        error_rate = float(metrics.get("error_rate", 1))
        db_failing = bool(database.get("failing", True))
        recent_errors = [line for line in logs if "error" in str(line).lower()]

        recovered = error_rate < 0.02 and not db_failing and not recent_errors
        notes = (
            "Recovery verified: error-rate normalized, database healthy, and logs clear."
            if recovered
            else "Recovery not verified: one or more health signals remain degraded."
        )
        return recovered, notes
