"""Machine validation reports kept separate from scientific assessment."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable


class ValidationSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"


@dataclass(frozen=True, slots=True, order=True)
class ValidationFinding:
    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    object_id: str | None = None
    json_pointer: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity.value,
            "object_id": self.object_id,
            "json_pointer": self.json_pointer,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    report_id: str
    run_id: str
    category: str
    findings: tuple[ValidationFinding, ...] = field(default_factory=tuple)

    @classmethod
    def from_findings(
        cls,
        report_id: str,
        run_id: str,
        category: str,
        findings: Iterable[ValidationFinding],
    ) -> "ValidationReport":
        return cls(report_id, run_id, category, tuple(findings))

    @property
    def passed(self) -> bool:
        return not any(item.severity == ValidationSeverity.ERROR for item in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "category": self.category,
            "passed": self.passed,
            "findings": [item.to_dict() for item in self.findings],
        }


__all__ = ["ValidationFinding", "ValidationReport", "ValidationSeverity"]
