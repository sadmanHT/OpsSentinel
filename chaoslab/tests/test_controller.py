import pytest
from fastapi import HTTPException

from chaoslab.controller import validate_fault_target
from chaoslab.models import FaultSpec, FaultType


def test_valid_fault_target_is_accepted() -> None:
    validate_fault_target(FaultSpec(fault=FaultType.N_PLUS_ONE, service="checkout"))
    validate_fault_target(FaultSpec(fault=FaultType.BROKEN_CONFIG, service="payment"))


def test_unknown_service_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_fault_target(FaultSpec(fault=FaultType.N_PLUS_ONE, service="unknown"))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "unknown service"


def test_fault_service_mismatch_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_fault_target(FaultSpec(fault=FaultType.N_PLUS_ONE, service="payment"))

    assert exc_info.value.status_code == 422
    assert "not supported" in str(exc_info.value.detail)
