import runpy
from pathlib import Path


HELPERS = runpy.run_path(str(Path(__file__).with_name("phase5-operational-smoke.py")))


def run_rejected_matrix() -> None:
    prepare_functions = [
        HELPERS["prepare_n_plus_one"],
        HELPERS["prepare_connection_leak"],
        HELPERS["prepare_disk_exhaustion"],
        HELPERS["prepare_broken_config"],
        HELPERS["prepare_memory_leak"],
    ]
    start_operational_run = HELPERS["start_operational_run"]
    assert_waiting_for_approval = HELPERS["assert_waiting_for_approval"]
    decide = HELPERS["decide"]
    assert_non_approved = HELPERS["assert_non_approved"]
    restore_all = HELPERS["restore_all"]
    assert_global_safety_invariants = HELPERS["assert_global_safety_invariants"]

    for index, prepare in enumerate(prepare_functions, start=1):
        payload, expected_code, fault, service = prepare()
        payload["scenario_id"] = f"phase5-rejected-matrix-{index}-{fault}"
        paused = start_operational_run(payload)
        assert_waiting_for_approval(paused, expected_code)
        actor = f"phase5-ci-rejector-{index}"
        completed = decide(paused["run_id"], "rejected", actor)
        assert_non_approved(
            completed,
            decision="rejected",
            fault=fault,
            service=service,
            actor=actor,
        )
        restore_all()

    assert_global_safety_invariants()
    print(
        "Phase 5 rejected-action matrix passed: all five core incidents paused at R2, "
        "executed no rollback, persisted rejection, and preserved the injected fault"
    )


if __name__ == "__main__":
    HELPERS["wait_for_backend"]()
    run_rejected_matrix()
    HELPERS["restore_all"]()
    assert HELPERS["list_faults"]() == []
