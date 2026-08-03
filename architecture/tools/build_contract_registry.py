#!/usr/bin/env python3
"""Build the complete phase-contract registry from the five reviewable contracts."""

from __future__ import annotations

import json
from pathlib import Path


ARCHITECTURE = Path(__file__).resolve().parents[1]
CONTRACTS = ARCHITECTURE / "contracts"
PHASE_IDS = ("P1", "P2", "P3", "P4", "P5")


def main() -> None:
    phases = []
    for phase_id in PHASE_IDS:
        path = CONTRACTS / "phases" / f"{phase_id}.json"
        phases.append(json.loads(path.read_text(encoding="utf-8")))

    registry = {"schema_version": "1.0.0", "contracts": phases}
    target = CONTRACTS / "phases.json"
    temporary = CONTRACTS / "phases.json.tmp"
    temporary.write_text(
        json.dumps(registry, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(target)
    print(f"Wrote {target.relative_to(ARCHITECTURE.parent)} with {len(phases)} contracts.")


if __name__ == "__main__":
    main()
