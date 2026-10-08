"""Enforce per-group coverage minimums (core, errors and webhooks >= 90%; total >= 85%).

Usage (after ``coverage run -m pytest``)::

    uv run coverage json -o coverage.json
    uv run python scripts/check_coverage.py coverage.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

GROUPS = {
    "nfeio._core": ("src/nfeio/_core/", 90.0),
    "nfeio.errors": ("src/nfeio/errors.py", 90.0),
    "nfeio.webhooks": ("src/nfeio/webhooks.py", 90.0),
}
TOTAL_MINIMUM = 85.0


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def main(path: str) -> int:
    data = json.loads(Path(path).read_text("utf-8"))
    files = data["files"]
    failures = []
    for name, (prefix, minimum) in GROUPS.items():
        covered = total = 0
        for filename, info in files.items():
            if prefix in filename.replace("\\", "/"):
                summary = info["summary"]
                covered += summary["covered_lines"] + summary.get("covered_branches", 0)
                total += summary["num_statements"] + summary.get("num_branches", 0)
        percent = _percent(covered, total)
        print(f"{name:<16} {percent:6.2f}% (min {minimum:.0f}%)")
        if total == 0 or percent < minimum:
            failures.append(name)
    total_percent = float(data["totals"]["percent_covered"])
    print(f"{'total':<16} {total_percent:6.2f}% (min {TOTAL_MINIMUM:.0f}%)")
    if total_percent < TOTAL_MINIMUM:
        failures.append("total")
    if failures:
        print("coverage below minimum: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "coverage.json"))
