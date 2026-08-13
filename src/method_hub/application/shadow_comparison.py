"""Shadow mode comparison harness (HV-7.2).

Runs the new classified policy alongside the old all-ERROR policy and
records disagreements.  Used during the pilot period to quantify the
false-rejection fix rate before any new run.

Two evidence sources:
1. Live runs during the pilot period.
2. Replay of historical role closures and validation reports.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from ..domain.validation import (
    FindingClass,
    ValidationFinding,
    ValidationReport,
    get_policy,
)


@dataclass(frozen=True, slots=True)
class ShadowComparison:
    """One comparison between old and new validation decisions."""

    run_id: str
    role_closure_id: str
    old_decision: Literal["passed", "failed", "rejected"]
    old_blocking_codes: tuple[str, ...]
    new_decision: Literal["passed", "correction_required", "rejected"]
    new_blocking_codes: tuple[str, ...]
    new_advisory_codes: tuple[str, ...]
    disagreement: bool
    disagreement_reason: str | None = None

    @property
    def is_false_rejection_fixed(self) -> bool:
        """Old=failed/rejected but new=passed or correction_required."""
        return (
            self.old_decision in ("failed", "rejected")
            and self.new_decision in ("passed", "correction_required")
        )

    @property
    def is_new_catch(self) -> bool:
        """Old=passed but new=rejected — new policy caught something."""
        return self.old_decision == "passed" and self.new_decision == "rejected"

    @property
    def is_recovery_enabled(self) -> bool:
        """Old=failed and new=correction_required — recovery now possible."""
        return (
            self.old_decision == "failed"
            and self.new_decision == "correction_required"
        )


def compare_findings(
    *,
    run_id: str,
    role_closure_id: str,
    findings: list[ValidationFinding],
) -> ShadowComparison:
    """Compare old vs new policy decisions for a set of findings.

    The OLD policy: every finding with severity=ERROR blocks.
    The NEW policy: only findings with blocks_publication=True block.
    """
    old_blocking: list[str] = []
    new_blocking: list[str] = []
    new_advisory: list[str] = []

    for f in findings:
        # OLD policy: ERROR severity = blocking
        if f.severity.value == "error":
            old_blocking.append(f.code)

        # NEW policy: blocks_publication flag
        if f.blocks_publication:
            new_blocking.append(f.code)
        else:
            new_advisory.append(f.code)

    old_decision: Literal["passed", "failed", "rejected"]
    old_decision = "failed" if old_blocking else "passed"

    new_decision: Literal["passed", "correction_required", "rejected"]
    if not new_blocking:
        new_decision = "passed"
    elif any(
        get_policy(c).finding_class == FindingClass.INTEGRITY_BLOCKER
        for c in new_blocking
    ):
        new_decision = "rejected"
    else:
        new_decision = "correction_required"

    disagreement = old_decision != new_decision or set(old_blocking) != set(
        new_blocking
    )

    reason: str | None = None
    if disagreement:
        if old_blocking and not new_blocking:
            reason = "old policy blocked on findings that new policy classifies as advisory"
        elif old_blocking and new_blocking and set(old_blocking) != set(new_blocking):
            reason = "blocking finding sets differ"
        elif not old_blocking and new_blocking:
            reason = "new policy catches what old policy missed"

    return ShadowComparison(
        run_id=run_id,
        role_closure_id=role_closure_id,
        old_decision=old_decision,
        old_blocking_codes=tuple(sorted(set(old_blocking))),
        new_decision=new_decision,
        new_blocking_codes=tuple(sorted(set(new_blocking))),
        new_advisory_codes=tuple(sorted(set(new_advisory))),
        disagreement=disagreement,
        disagreement_reason=reason,
    )


@dataclass(frozen=True, slots=True)
class ShadowComparisonSummary:
    """Aggregate metrics from a batch of shadow comparisons."""

    total_comparisons: int
    agreements: int
    disagreements: int
    false_rejections_fixed: int
    new_catches: int
    recovery_enabled: int
    old_blocking_rate: float
    new_blocking_rate: float
    improvement_rate: float

    @classmethod
    def from_comparisons(
        cls, comparisons: list[ShadowComparison]
    ) -> "ShadowComparisonSummary":
        total = len(comparisons)
        if total == 0:
            return cls(0, 0, 0, 0, 0, 0, 0.0, 0.0, 0.0)
        disagreements = sum(1 for c in comparisons if c.disagreement)
        agreements = total - disagreements
        false_fixed = sum(1 for c in comparisons if c.is_false_rejection_fixed)
        catches = sum(1 for c in comparisons if c.is_new_catch)
        recovery = sum(1 for c in comparisons if c.is_recovery_enabled)
        old_blocked = sum(
            1 for c in comparisons if c.old_decision != "passed"
        )
        new_blocked = sum(
            1 for c in comparisons if c.new_decision != "passed"
        )
        old_rate = old_blocked / total
        new_rate = new_blocked / total
        improvement = old_rate - new_rate
        return cls(
            total_comparisons=total,
            agreements=agreements,
            disagreements=disagreements,
            false_rejections_fixed=false_fixed,
            new_catches=catches,
            recovery_enabled=recovery,
            old_blocking_rate=old_rate,
            new_blocking_rate=new_rate,
            improvement_rate=improvement,
        )


__all__ = [
    "ShadowComparison",
    "ShadowComparisonSummary",
    "compare_findings",
]
