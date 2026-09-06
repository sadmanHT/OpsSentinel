from __future__ import annotations

from pathlib import Path

from evaluationlab.models import CalibrationBin


def reliability_diagram_svg(
    bins: list[CalibrationBin],
    *,
    width: int = 640,
    height: int = 480,
) -> str:
    if width < 240 or height < 240:
        raise ValueError("reliability diagram dimensions must be at least 240 pixels")
    if not bins:
        raise ValueError("at least one calibration bin is required")

    margin = 56
    plot_width = width - 2 * margin
    plot_height = height - 2 * margin

    def x(value: float) -> float:
        return margin + value * plot_width

    def y(value: float) -> float:
        return height - margin - value * plot_height

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">Reliability diagram</title>',
        '<desc id="desc">Predicted confidence versus empirical accuracy.</desc>',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>',
        f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" '
        f'y2="{height - margin}" stroke="black"/>',
        f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" '
        'stroke="black"/>',
        f'<line x1="{x(0):.2f}" y1="{y(0):.2f}" x2="{x(1):.2f}" y2="{y(1):.2f}" '
        'stroke="black" stroke-dasharray="6 6" opacity="0.55"/>',
        f'<text x="{width / 2:.2f}" y="{height - 14}" text-anchor="middle" '
        'font-family="sans-serif" font-size="14">Mean confidence</text>',
        f'<text x="18" y="{height / 2:.2f}" text-anchor="middle" '
        'font-family="sans-serif" font-size="14" '
        f'transform="rotate(-90 18 {height / 2:.2f})">Empirical accuracy</text>',
    ]

    for tick in range(6):
        value = tick / 5
        parts.append(
            f'<text x="{x(value):.2f}" y="{height - margin + 22}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="11">{value:.1f}</text>'
        )
        parts.append(
            f'<text x="{margin - 10}" y="{y(value) + 4:.2f}" text-anchor="end" '
            f'font-family="sans-serif" font-size="11">{value:.1f}</text>'
        )

    for item in sorted(bins, key=lambda value: (value.lower_bound, value.upper_bound)):
        parts.append(
            f'<circle cx="{x(item.mean_confidence):.2f}" '
            f'cy="{y(item.empirical_accuracy):.2f}" r="5" fill="black">'
            f'<title>{item.lower_bound:.2f}-{item.upper_bound:.2f}: '
            f'confidence={item.mean_confidence:.4f}, accuracy={item.empirical_accuracy:.4f}, '
            f'n={item.count}</title></circle>'
        )

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_reliability_diagram(path: Path, bins: list[CalibrationBin]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reliability_diagram_svg(bins), encoding="utf-8")
    return path
