from pathlib import Path

import pytest

from evaluationlab.models import CalibrationBin
from evaluationlab.reporting import reliability_diagram_svg, write_reliability_diagram


def _bins() -> list[CalibrationBin]:
    return [
        CalibrationBin(
            lower_bound=0.0,
            upper_bound=0.5,
            count=2,
            mean_confidence=0.25,
            empirical_accuracy=0.5,
            absolute_gap=0.25,
        ),
        CalibrationBin(
            lower_bound=0.5,
            upper_bound=1.0,
            count=3,
            mean_confidence=0.8,
            empirical_accuracy=2 / 3,
            absolute_gap=abs(0.8 - (2 / 3)),
        ),
    ]


def test_reliability_diagram_svg_is_deterministic_and_contains_calibration_points() -> None:
    first = reliability_diagram_svg(_bins())
    second = reliability_diagram_svg(list(reversed(_bins())))

    assert first == second
    assert first.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "Reliability diagram" in first
    assert "stroke-dasharray=\"6 6\"" in first
    assert "confidence=0.2500, accuracy=0.5000, n=2" in first
    assert "confidence=0.8000, accuracy=0.6667, n=3" in first
    assert first.count("<circle ") == 2


def test_write_reliability_diagram_round_trips_exact_svg(tmp_path: Path) -> None:
    path = tmp_path / "reports" / "reliability.svg"
    returned = write_reliability_diagram(path, _bins())

    assert returned == path
    assert path.read_text(encoding="utf-8") == reliability_diagram_svg(_bins())


def test_reliability_diagram_rejects_empty_bins_or_tiny_canvas() -> None:
    with pytest.raises(ValueError, match="at least one"):
        reliability_diagram_svg([])
    with pytest.raises(ValueError, match="at least 240"):
        reliability_diagram_svg(_bins(), width=200)
