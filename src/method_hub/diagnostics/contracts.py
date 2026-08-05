"""Versioned contracts for the diagnostic lane.

This module defines the data contracts that H0.1 requires:

* :class:`ProfileManifest` — exact project ID, role, profile name, SOUL
  digest, config digest, exact skills, memory policy and version, profile
  revision, and provisioning provenance.
* :class:`DiagnosticContract` — the fixed synthetic task, its output
  contract, and rejecting validators.
* :class:`MemorySnapshotContract` — before/after snapshot with digests.
* :class:`ProcessIdentity` — durable runtime identity for one process.
* :class:`StateTransition` — the diagnostic lifecycle state machine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

# --------------------------------------------------------------------------- #
# Memory policy (re-exported from profiles for contract consumers)             #
# --------------------------------------------------------------------------- #


class MemoryPolicyVersion(StrEnum):
    """Version of the memory-policy contract."""

    V1 = "1.0.0"


# --------------------------------------------------------------------------- #
# Profile manifest                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SkillDeclaration:
    """One declared skill with its source and version."""

    skill_id: str
    source: str = ""
    recommended_version: str = ""


@dataclass(frozen=True, slots=True)
class ProfileManifest:
    """Versioned manifest of a provisioned project role profile.

    Contains exact project ID, mapped Hermes profile name, SOUL/config/skill
    digests, exact skill names and versions, memory policy and policy
    version, profile revision, and provisioning provenance.
    """

    format: str = "method-hub.profile-manifest"
    format_version: str = "1.0.0"
    project_id: str = ""
    role: str = ""
    profile_name: str = ""
    soul_sha256: str = "0" * 64
    config_sha256: str = "0" * 64
    skills: tuple[SkillDeclaration, ...] = ()
    memory_policy: str = "persistent"
    memory_policy_version: str = MemoryPolicyVersion.V1.value
    profile_revision: int = 1
    provisioning_provenance: str = ""
    runtime_compatibility: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "format_version": self.format_version,
            "project_id": self.project_id,
            "role": self.role,
            "profile_name": self.profile_name,
            "soul_sha256": self.soul_sha256,
            "config_sha256": self.config_sha256,
            "skills": [
                {
                    "skill_id": s.skill_id,
                    "source": s.source,
                    "recommended_version": s.recommended_version,
                }
                for s in self.skills
            ],
            "memory_policy": self.memory_policy,
            "memory_policy_version": self.memory_policy_version,
            "profile_revision": self.profile_revision,
            "provisioning_provenance": self.provisioning_provenance,
            "runtime_compatibility": dict(self.runtime_compatibility),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @property
    def manifest_sha256(self) -> str:
        return hashlib.sha256(
            self.to_json().encode("utf-8")
        ).hexdigest()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProfileManifest":
        skills = tuple(
            SkillDeclaration(
                skill_id=str(s["skill_id"]),
                source=str(s.get("source", "")),
                recommended_version=str(s.get("recommended_version", "")),
            )
            for s in data.get("skills", [])
        )
        return cls(
            format=str(data.get("format", "method-hub.profile-manifest")),
            format_version=str(data.get("format_version", "1.0.0")),
            project_id=str(data.get("project_id", "")),
            role=str(data.get("role", "")),
            profile_name=str(data.get("profile_name", "")),
            soul_sha256=str(data.get("soul_sha256", "0" * 64)),
            config_sha256=str(data.get("config_sha256", "0" * 64)),
            skills=skills,
            memory_policy=str(data.get("memory_policy", "persistent")),
            memory_policy_version=str(
                data.get("memory_policy_version", MemoryPolicyVersion.V1.value)
            ),
            profile_revision=int(data.get("profile_revision", 1)),
            provisioning_provenance=str(data.get("provisioning_provenance", "")),
            runtime_compatibility=dict(data.get("runtime_compatibility", {})),
        )


class ProfileManifestValidationError(ValueError):
    """Raised when a profile manifest fails validation."""


def validate_profile_manifest(manifest: ProfileManifest) -> list[str]:
    """Validate a profile manifest.  Returns a list of findings (empty = valid)."""
    findings: list[str] = []
    if not manifest.project_id:
        findings.append("project_id must not be empty")
    if not manifest.role:
        findings.append("role must not be empty")
    if not manifest.profile_name:
        findings.append("profile_name must not be empty")
    if manifest.soul_sha256 == "0" * 64:
        findings.append("soul_sha256 must not be the zero hash")
    if manifest.profile_revision < 1:
        findings.append("profile_revision must be >= 1")
    if manifest.memory_policy not in ("persistent", "read_only", "ephemeral"):
        findings.append(f"unknown memory_policy {manifest.memory_policy!r}")
    if len(manifest.soul_sha256) != 64:
        findings.append("soul_sha256 must be 64 hex chars")
    if len(manifest.config_sha256) != 64:
        findings.append("config_sha256 must be 64 hex chars")
    # No project research question or mutable method state in SOUL.md.
    # We can't check SOUL content here (only its digest), but the provisioning
    # step must enforce this rule before computing the digest.
    return findings


# --------------------------------------------------------------------------- #
# Diagnostic contract — the fixed synthetic task                               #
# --------------------------------------------------------------------------- #


#: The fixed diagnostic task prompt.  The agent must read a brief file and
#: produce a small deterministic output file whose content can be validated
#: independently of prose.
DIAGNOSTIC_TASK_PROMPT = (
    'Read the task brief at {brief_path}. '
    'Then write a JSON object to {output_path} with exactly these fields: '
    '"status" (the string "ok"), "brief_sha256" (the SHA-256 hex of the '
    'task brief file content), and "agent_profile" (your profile name). '
    'Write only that file.'
)

#: The expected output schema for the diagnostic task.
DIAGNOSTIC_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["ok"]},
        "brief_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "agent_profile": {"type": "string"},
    },
    "required": ["status", "brief_sha256", "agent_profile"],
    "additionalProperties": False,
}


@dataclass(frozen=True, slots=True)
class DiagnosticOutputContract:
    """Contract for the fixed synthetic diagnostic task output."""

    output_filename: str = "diagnostic_result.json"
    expected_status: str = "ok"
    schema: Mapping[str, Any] = field(
        default_factory=lambda: dict(DIAGNOSTIC_OUTPUT_SCHEMA)
    )

    @property
    def brief_sha256_field(self) -> str:
        return "brief_sha256"

    @property
    def status_field(self) -> str:
        return "status"

    @property
    def agent_profile_field(self) -> str:
        return "agent_profile"


def validate_diagnostic_output(
    output_content: str | bytes,
    *,
    expected_brief_sha256: str,
    expected_profile: str,
) -> list[str]:
    """Validate the diagnostic output against its contract.

    Returns a list of findings (empty = valid).  This is a rejecting
    validator — it checks structure, content, and cross-references.
    """
    findings: list[str] = []
    if isinstance(output_content, bytes):
        try:
            output_content = output_content.decode("utf-8")
        except UnicodeDecodeError:
            return ["output is not valid UTF-8"]

    try:
        data = json.loads(output_content)
    except json.JSONDecodeError as exc:
        return [f"output is not valid JSON: {exc}"]

    if not isinstance(data, dict):
        return ["output must be a JSON object"]

    # Check required fields.
    for field_name in ("status", "brief_sha256", "agent_profile"):
        if field_name not in data:
            findings.append(f"missing required field: {field_name}")

    if findings:
        return findings

    if data.get("status") != "ok":
        findings.append(f"status must be 'ok', got {data.get('status')!r}")

    if data.get("brief_sha256") != expected_brief_sha256:
        findings.append(
            f"brief_sha256 mismatch: expected {expected_brief_sha256[:16]}..., "
            f"got {str(data.get('brief_sha256'))[:16]}..."
        )

    if data.get("agent_profile") != expected_profile:
        findings.append(
            f"agent_profile mismatch: expected {expected_profile!r}, "
            f"got {data.get('agent_profile')!r}"
        )

    if len(data) > 3:
        extra = sorted(set(data) - {"status", "brief_sha256", "agent_profile"})
        findings.append(f"unexpected additional fields: {extra}")

    return findings


# --------------------------------------------------------------------------- #
# Memory snapshot contract                                                      #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """An immutable content-addressed snapshot of profile memory state."""

    memory_sha256: str | None
    user_sha256: str | None
    session_count: int
    state_db_size: int
    captured_at: str
    policy: str = "persistent"

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_sha256": self.memory_sha256,
            "user_sha256": self.user_sha256,
            "session_count": self.session_count,
            "state_db_size": self.state_db_size,
            "captured_at": self.captured_at,
            "policy": self.policy,
        }


# --------------------------------------------------------------------------- #
# Process identity contract                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """Durable runtime identity for one diagnostic execution.

    Trusted local execution (ADR-012): boot_id, PID, proc start ticks,
    executable identity, process group, and an invocation marker.
    Historical records may carry OCI container IDs and image digests.
    """

    runtime: str  # executor runtime label, e.g. "local"; historical: "bwrap"/"oci"
    external_id: str  # e.g. "local:pid:12345:st:123456:mk:abc123def456"
    pid: int | None = None
    boot_id: str | None = None
    proc_start_ticks: int | None = None
    executable_path: str | None = None
    process_group: int | None = None
    invocation_marker: str | None = None
    container_id: str | None = None
    image_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "runtime": self.runtime,
            "external_id": self.external_id,
            "pid": self.pid,
            "boot_id": self.boot_id,
            "proc_start_ticks": self.proc_start_ticks,
            "executable_path": self.executable_path,
            "process_group": self.process_group,
            "invocation_marker": self.invocation_marker,
            "container_id": self.container_id,
            "image_digest": self.image_digest,
        }


# --------------------------------------------------------------------------- #
# State transition contract                                                    #
# --------------------------------------------------------------------------- #


class DiagnosticState(StrEnum):
    """Diagnostic lifecycle states (H0.6)."""

    PENDING = "pending"
    PREFLIGHT = "preflight"
    CREATING = "creating"
    LAUNCH_ACKNOWLEDGED = "launch_acknowledged"
    RUNNING = "running"
    CLOSING = "closing"
    CANCEL_REQUESTED = "cancel_requested"
    TIMEOUT_REQUESTED = "timeout_requested"
    TERMINATING = "terminating"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    UNRESOLVED = "unresolved"


#: Allowed state transitions (H0.6).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    DiagnosticState.PENDING: frozenset({
        DiagnosticState.PREFLIGHT,
        DiagnosticState.CANCEL_REQUESTED,
        DiagnosticState.FAILED,
    }),
    DiagnosticState.PREFLIGHT: frozenset({
        DiagnosticState.CREATING,
        DiagnosticState.CANCEL_REQUESTED,
        DiagnosticState.FAILED,
    }),
    DiagnosticState.CREATING: frozenset({
        DiagnosticState.LAUNCH_ACKNOWLEDGED,
        DiagnosticState.CANCEL_REQUESTED,
        DiagnosticState.TERMINATING,
        DiagnosticState.FAILED,
    }),
    DiagnosticState.LAUNCH_ACKNOWLEDGED: frozenset({
        DiagnosticState.RUNNING,
        DiagnosticState.CANCEL_REQUESTED,
        DiagnosticState.TERMINATING,
        DiagnosticState.FAILED,
    }),
    DiagnosticState.RUNNING: frozenset({
        DiagnosticState.CLOSING,
        DiagnosticState.CANCEL_REQUESTED,
        DiagnosticState.TIMEOUT_REQUESTED,
        DiagnosticState.TERMINATING,
        DiagnosticState.FAILED,
    }),
    DiagnosticState.CLOSING: frozenset({
        DiagnosticState.SUCCEEDED,
        DiagnosticState.FAILED,
    }),
    DiagnosticState.CANCEL_REQUESTED: frozenset({
        DiagnosticState.CANCELLED,
    }),
    DiagnosticState.TIMEOUT_REQUESTED: frozenset({
        DiagnosticState.TERMINATING,
    }),
    DiagnosticState.TERMINATING: frozenset({
        DiagnosticState.CANCELLED,
        DiagnosticState.TIMED_OUT,
        DiagnosticState.FAILED,
        DiagnosticState.UNRESOLVED,
    }),
}

#: Terminal states — once entered, the status cannot change.
TERMINAL_DIAGNOSTIC_STATES: frozenset[str] = frozenset({
    DiagnosticState.SUCCEEDED,
    DiagnosticState.FAILED,
    DiagnosticState.CANCELLED,
    DiagnosticState.TIMED_OUT,
    DiagnosticState.UNRESOLVED,
})

#: States where the process is running or about to run.
ACTIVE_STATES: frozenset[str] = frozenset({
    DiagnosticState.PREFLIGHT,
    DiagnosticState.CREATING,
    DiagnosticState.LAUNCH_ACKNOWLEDGED,
    DiagnosticState.RUNNING,
    DiagnosticState.CLOSING,
    DiagnosticState.TERMINATING,
})


def is_valid_transition(from_state: str, to_state: str) -> bool:
    """Check whether a state transition is allowed."""
    if from_state in TERMINAL_DIAGNOSTIC_STATES:
        return False
    allowed = ALLOWED_TRANSITIONS.get(from_state, frozenset())
    return to_state in allowed


class StateTransitionError(RuntimeError):
    """Raised when an invalid state transition is attempted."""


# --------------------------------------------------------------------------- #
# Usage report contract                                                        #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class UsageReport:
    """Parsed ``--usage-file`` JSON report from a Hermes one-shot run."""

    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    api_calls: int = 0
    completed: bool = False
    failed: bool = False
    session_id: str = ""
    cost_status: str = "unknown"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UsageReport":
        return cls(
            model=str(data.get("model", "")),
            provider=str(data.get("provider", "")),
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            total_tokens=int(data.get("total_tokens", 0)),
            api_calls=int(data.get("api_calls", 0)),
            completed=bool(data.get("completed", False)),
            failed=bool(data.get("failed", False)),
            session_id=str(data.get("session_id", "")),
            cost_status=str(data.get("cost_status", "unknown")),
        )

    @classmethod
    def from_json_file(cls, path: Path) -> "UsageReport | None":
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return cls.from_dict(data)


__all__ = [
    "ALLOWED_TRANSITIONS",
    "ACTIVE_STATES",
    "DiagnosticOutputContract",
    "DiagnosticState",
    "MemoryPolicyVersion",
    "MemorySnapshot",
    "ProcessIdentity",
    "ProfileManifest",
    "ProfileManifestValidationError",
    "SkillDeclaration",
    "StateTransitionError",
    "TERMINAL_DIAGNOSTIC_STATES",
    "UsageReport",
    "DIAGNOSTIC_OUTPUT_SCHEMA",
    "DIAGNOSTIC_TASK_PROMPT",
    "is_valid_transition",
    "validate_diagnostic_output",
    "validate_profile_manifest",
]
