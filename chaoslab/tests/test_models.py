import pytest
from pydantic import ValidationError

from chaoslab.models import FaultSpec, FaultType, Severity


def test_fault_spec_is_deterministic_and_strict() -> None:
    spec = FaultSpec(fault=FaultType.N_PLUS_ONE, service="checkout", seed=99)
    assert spec.seed == 99
    assert spec.severity == Severity.P2


def test_fault_spec_rejects_unknown_fault() -> None:
    with pytest.raises(ValidationError):
        FaultSpec(fault="unknown", service="checkout")  # type: ignore[arg-type]
