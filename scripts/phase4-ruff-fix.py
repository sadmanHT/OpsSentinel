from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text()
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}, found {count}: {old!r}")
    target.write_text(text.replace(old, new, 1))


replace_once(
    "backend/app/agent/providers.py",
    "    PlanStep,\n    ProviderUsage,\n    ProposedAction,\n",
    "    PlanStep,\n    ProposedAction,\n    ProviderUsage,\n",
)

provider_replacements = {
    '                    "Checkout performs excessive per-request database queries consistent with an N+1 query regression.",': (
        '                    (\n'
        '                        "Checkout performs excessive per-request database queries "\n'
        '                        "consistent with an N+1 query regression."\n'
        '                    ),'
    ),
    '                    "Checkout database query fan-out is abnormally high and may indicate an N+1 query regression.",': (
        '                    (\n'
        '                        "Checkout database query fan-out is abnormally high and may "\n'
        '                        "indicate an N+1 query regression."\n'
        '                    ),'
    ),
    '                    "Inventory exhausts its database connection capacity, consistent with a connection leak.",': (
        '                    (\n'
        '                        "Inventory exhausts its database connection capacity, "\n'
        '                        "consistent with a connection leak."\n'
        '                    ),'
    ),
    '                    "Worker disk capacity is exhausted and requests fail with insufficient-storage errors.",': (
        '                    (\n'
        '                        "Worker disk capacity is exhausted and requests fail with "\n'
        '                        "insufficient-storage errors."\n'
        '                    ),'
    ),
    '                    "Worker resource growth culminates in a restart and 503 failure, consistent with a memory leak.",': (
        '                    (\n'
        '                        "Worker resource growth culminates in a restart and 503 failure, "\n'
        '                        "consistent with a memory leak."\n'
        '                    ),'
    ),
    '                    "Payment rejects requests with authentication/configuration failures and the gateway surfaces the dependency failure.",': (
        '                    (\n'
        '                        "Payment rejects requests with authentication/configuration "\n'
        '                        "failures and the gateway surfaces the dependency failure."\n'
        '                    ),'
    ),
    '                "Review the recent checkout data-access change and replace repeated per-item queries with an eager-loaded or batched query, then rerun latency and query-count verification.",': (
        '                (\n'
        '                    "Review the recent checkout data-access change and replace repeated "\n'
        '                    "per-item queries with an eager-loaded or batched query, then rerun "\n'
        '                    "latency and query-count verification."\n'
        '                ),'
    ),
    '                "Fix inventory connection lifecycle handling and verify connections are released on success and failure paths.",': (
        '                (\n'
        '                    "Fix inventory connection lifecycle handling and verify connections "\n'
        '                    "are released on success and failure paths."\n'
        '                ),'
    ),
    '                "Free or rotate worker output safely, then add bounded retention and disk-pressure protection.",': (
        '                (\n'
        '                    "Free or rotate worker output safely, then add bounded retention and "\n'
        '                    "disk-pressure protection."\n'
        '                ),'
    ),
    '                "Identify the retained worker allocation path, bound or release retained objects, and verify memory remains stable under repeated work.",': (
        '                (\n'
        '                    "Identify the retained worker allocation path, bound or release "\n'
        '                    "retained objects, and verify memory remains stable under repeated work."\n'
        '                ),'
    ),
    '                "Correct the payment authentication/configuration value through the approved deployment process and verify both payment and gateway health.",': (
        '                (\n'
        '                    "Correct the payment authentication/configuration value through the "\n'
        '                    "approved deployment process and verify both payment and gateway health."\n'
        '                ),'
    ),
}
for old, new in provider_replacements.items():
    replace_once("backend/app/agent/providers.py", old, new)

replace_once(
    "backend/app/agent/runtime.py",
    "                if not step.completed and step.tool == invocation.tool and step.arguments == invocation.arguments:",
    "                if (\n"
    "                    not step.completed\n"
    "                    and step.tool == invocation.tool\n"
    "                    and step.arguments == invocation.arguments\n"
    "                ):",
)
replace_once(
    "backend/app/agent/runtime.py",
    '                primary_root_cause="Investigation stopped before a primary root cause could be established.",',
    "                primary_root_cause=(\n"
    '                    "Investigation stopped before a primary root cause could be established."\n'
    "                ),",
)
replace_once(
    "backend/app/agent/store.py",
    "                        contradicting_evidence=[str(value) for value in item.contradicting_evidence],",
    "                        contradicting_evidence=[\n"
    "                            str(value) for value in item.contradicting_evidence\n"
    "                        ],",
)
replace_once(
    "backend/tests/test_agent_runtime.py",
    '                summary="Deliberately repeat one legal tool call to exercise the repetition budget.",',
    "                summary=(\n"
    '                    "Deliberately repeat one legal tool call to exercise the repetition "\n'
    '                    "budget."\n'
    "                ),",
)

print("Applied exact Phase 4 Ruff fixes")
