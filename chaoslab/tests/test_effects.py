from chaoslab.effects import deterministic_rng
from chaoslab.models import FaultState, FaultType


def test_fault_rng_reproducible_for_same_state() -> None:
    state = FaultState(fault=FaultType.N_PLUS_ONE, service="checkout", seed=12)
    first = deterministic_rng(state, 4).random()
    second = deterministic_rng(state, 4).random()
    assert first == second
