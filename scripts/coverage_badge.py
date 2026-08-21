#!/usr/bin/env python3
"""
Generate a coverage badge SVG from coverage data.

Written in-tree on purpose: the coverage-badge package depends on pkg_resources
and breaks on Python 3.12+, and this needs no dependencies beyond coverage.

Usage:
    python scripts/coverage_badge.py [output.svg]
"""

import json
import subprocess
import sys
from pathlib import Path

# shields.io thresholds, lowest first
COLORS = [
    (0, "#e05d44"),  # red
    (65, "#dfb317"),  # yellow
    (80, "#a4a61d"),  # yellowgreen
    (90, "#97ca00"),  # green
    (95, "#4c1"),  # brightgreen
]

TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{total}" height="20" role="img" aria-label="coverage: {pct}%">
  <title>coverage: {pct}%</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_w}" height="20" fill="#555"/>
    <rect x="{label_w}" width="{value_w}" height="20" fill="{color}"/>
    <rect width="{total}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="110" text-rendering="geometricPrecision">
    <text x="{label_x}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" textLength="{label_len}">coverage</text>
    <text x="{label_x}" y="140" transform="scale(.1)" textLength="{label_len}">coverage</text>
    <text x="{value_x}" y="150" fill="#010101" fill-opacity=".3" transform="scale(.1)" textLength="{value_len}">{pct}%</text>
    <text x="{value_x}" y="140" transform="scale(.1)" textLength="{value_len}">{pct}%</text>
  </g>
</svg>
"""


def read_percent() -> int:
    """Read total coverage percentage from the current .coverage data."""
    out = subprocess.run(
        [sys.executable, "-m", "coverage", "json", "-o", "-", "--quiet"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return round(json.loads(out)["totals"]["percent_covered"])


def pick_color(pct: int) -> str:
    color = COLORS[0][1]
    for threshold, value in COLORS:
        if pct >= threshold:
            color = value
    return color


def render(pct: int) -> str:
    label_w = 62
    value_w = 8 * len(f"{pct}%") + 14
    return TEMPLATE.format(
        pct=pct,
        color=pick_color(pct),
        label_w=label_w,
        value_w=value_w,
        total=label_w + value_w,
        label_x=label_w * 5,
        label_len=(label_w - 10) * 10,
        value_x=(label_w + value_w / 2) * 10,
        value_len=(value_w - 10) * 10,
    )


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "coverage.svg")
    pct = read_percent()
    out.write_text(render(pct))
    print(f"{out}: {pct}%")  # noqa: T201 — вывод для лога CI


if __name__ == "__main__":
    main()
