"""Post-execution output validation for supervised sealed runs (Block 5, WP-E1).

This service runs AFTER a launch closes (post-quiescence): it refuses to
validate a launch that is still ``running`` (or that has no launch record at
all) and then verifies the run's declared outputs against the immutable
manifest.  Exit code zero is never the result (ADR-012 item 5): the launch
record carries the exit code, but validation judges the *artifacts*.

Scope discipline
================

* The validator reads the run directory and the seal/launch registries and
  writes exactly one row into the ``run_validation_reports`` sibling table.
  It never modifies the immutable seal registry, the manifest, the run
  directory, or any launch record.
* Raw evidence first: before any judgment, the validator walks everything
  under ``run_dir/outputs`` and records the raw-output inventory (relative
  path, sha256, size, entry kind) into the report.  The inventory is captured
  before any check runs.
* Each concern is a named check with a ``pass``/``fail``/``skipped`` status
  and a human-readable detail.  Skipped checks do not fail the overall
  verdict and appear in the report for transparency.

Checks
======

1. ``inventory`` — every declared expected output (manifest entry with a
   concrete ``relative_path``/``path``, resolved under ``run_dir/outputs``)
   exists as a regular non-symlink, non-empty file; and NO undeclared file
   or symlink exists anywhere under ``outputs/`` (an undeclared file is a
   failure, not a warning).
2. ``safe_paths`` — every declared output path (and every declared
   companion) still resolves inside ``outputs/`` after normalization.
   Defense in depth: the preflight already checked this at seal time.
3. ``schema`` — for JSON outputs (declared path ends in ``.json`` or the
   entry names a schema), the file parses as strict JSON; when the entry
   declares ``required_fields``, each named top-level field must be present.
   Entries without ``required_fields`` skip field-level checks and say so.
4. ``nonempty_scientific_fields`` — for JSON outputs with declared required
   fields, no required field is null, an empty string, an empty array, or an
   empty object.  A present-but-empty scientific field is a failure.
5. ``companions`` — when an entry declares ``companions`` (e.g.
   ``['fig1.pdf']``), each companion exists next to the output, is a regular
   non-symlink non-empty file, and its sha256 is recorded in the report.
6. ``identity`` — when an output JSON carries run/method identity fields
   (``run_id``, ``invocation_id``, ``method_id``), they must match the
   manifest's values.  A wrong-basis output fails even when well-formed.
7. ``phase_consistency`` — reuses the phase-specific scientific validators
   (``harness/scientific_validators.py``) when the run's phase has one and
   the manifest declares outputs bound to that phase contract; otherwise the
   check is recorded as skipped-with-reason.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..contracts import ResolvedPhasePlan
from ..domain.identities import MethodIdentity, PhaseContractIdentity
from ..domain.runs import isoformat_utc, utc_now
from ..harness.publication import (
    RegisteredArtifactMetadata,
    RegisteredValidatedOutput,
)
from ..harness.scientific_validators import validate_phase_scientific
from ..json_io import JsonLoadError, loads_json
from .run_profile_assembler import RunProfileAssembler, RunSealError, SealedRun

#: Report document identity recorded in ``run_validation_reports``.
REPORT_FORMAT = "method-hub.output-validation-report"
REPORT_FORMAT_VERSION = "1.0.0"

#: Manifest keys that may declare an expected output path (mirrors the
#: launcher and the preflight).
_OUTPUT_PATH_KEYS = ("relative_path", "path")

#: Launch statuses that count as terminal (post-quiescence).
_TERMINAL_LAUNCH_STATUSES = frozenset({"succeeded", "failed", "cancelled"})

#: Phases with a phase-specific scientific validator to reuse.
_PHASE_VALIDATOR_PHASES = frozenset({"P1", "P2", "P3", "P4", "P5"})

#: Identity keys checked inside output JSON documents (check 6).  The run
#: id of a sealed run IS its invocation id (the launcher binds
#: ``run_id=invocation_id``), so both compare against the manifest's
#: invocation id.
_IDENTITY_KEYS = ("run_id", "invocation_id", "method_id")

#: Check statuses.
PASS = "pass"
FAIL = "fail"
SKIPPED = "skipped"


class OutputValidationError(RuntimeError):
    """A sealed run could not be validated."""


class LaunchNotClosedError(OutputValidationError):
    """Validation requires a terminal launch record; none is available."""


@dataclass(frozen=True, slots=True)
class RawOutputEntry:
    """One raw entry observed under ``outputs/`` before any judgment."""

    relative_path: str
    sha256: str
    size_bytes: int
    is_symlink: bool
    is_regular: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "is_symlink": self.is_symlink,
            "is_regular": self.is_regular,
        }


@dataclass(frozen=True, slots=True)
class OutputValidationCheck:
    """One named validation concern with a pass/fail/skipped verdict."""

    name: str
    status: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class OutputValidationReport:
    """The complete post-execution validation result for one launch."""

    launch_id: str
    seal_id: str
    invocation_id: str
    project_id: str
    phase: str
    role: str
    validated_at: str
    raw_inventory: tuple[RawOutputEntry, ...]
    checks: tuple[OutputValidationCheck, ...]
    digests: Mapping[str, str]

    @property
    def passed(self) -> bool:
        """Overall verdict: no failing check.  Skipped checks do not fail."""
        return not any(check.status == FAIL for check in self.checks)

    @property
    def verdict(self) -> str:
        return PASS if self.passed else FAIL

    def check(self, name: str) -> OutputValidationCheck | None:
        for item in self.checks:
            if item.name == name:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": REPORT_FORMAT,
            "format_version": REPORT_FORMAT_VERSION,
            "verdict": self.verdict,
            "launch_id": self.launch_id,
            "seal_id": self.seal_id,
            "invocation_id": self.invocation_id,
            "project_id": self.project_id,
            "phase": self.phase,
            "role": self.role,
            "validated_at": self.validated_at,
            "raw_inventory": [entry.to_dict() for entry in self.raw_inventory],
            "checks": [check.to_dict() for check in self.checks],
            "digests": dict(self.digests),
        }


# --------------------------------------------------------------------------- #
# Internal records                                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class _DeclaredOutput:
    """One manifest ``expected_outputs`` entry normalized for the checks."""

    index: int
    output_id: str
    path_value: str | None
    required: bool
    is_json: bool
    required_fields: tuple[str, ...]
    companions: tuple[str, ...]


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def _pass(name: str, detail: str) -> OutputValidationCheck:
    return OutputValidationCheck(name, PASS, detail)


def _fail(name: str, detail: str) -> OutputValidationCheck:
    return OutputValidationCheck(name, FAIL, detail)


def _skip(name: str, detail: str) -> OutputValidationCheck:
    return OutputValidationCheck(name, SKIPPED, detail)


def _resolve_seal(
    assembler: RunProfileAssembler, seal_or_invocation_id: SealedRun | str
) -> SealedRun:
    if isinstance(seal_or_invocation_id, SealedRun):
        return seal_or_invocation_id
    if isinstance(seal_or_invocation_id, str):
        record = assembler.store.find_by_invocation_id(seal_or_invocation_id)
        if record is None:
            raise RunSealError(
                f"No sealed run for invocation {seal_or_invocation_id!r}."
            )
        return assembler._reconstruct(record)  # verifies the manifest digest
    raise TypeError(
        "seal_or_invocation_id must be a SealedRun or an invocation id string"
    )


def _require_terminal_launch(
    assembler: RunProfileAssembler, invocation_id: str
) -> dict[str, Any]:
    """Return the terminal launch record for *invocation_id* or refuse.

    Post-quiescence rule: validation runs only after a launch closes.  A
    missing launch record or a ``running`` launch is rejected before any
    output byte is read.
    """
    launch = assembler.store.find_launch_record_by_invocation(invocation_id)
    if launch is None:
        raise LaunchNotClosedError(
            f"No launch record for invocation {invocation_id!r}; "
            "validation requires a terminal launch."
        )
    if launch["status"] not in _TERMINAL_LAUNCH_STATUSES:
        raise LaunchNotClosedError(
            f"Launch {launch['launch_id']!r} for invocation "
            f"{invocation_id!r} is not closed (status={launch['status']!r}); "
            "validation requires a terminal launch."
        )
    return launch


def _walk_raw_inventory(outputs_dir: Path) -> tuple[RawOutputEntry, ...]:
    """Record everything under ``outputs/`` before any judgment.

    Regular files are digested; symlinks and special entries are recorded
    with an empty digest (their content is never followed or read) so the
    raw evidence preserves their presence and kind.
    """
    entries: list[RawOutputEntry] = []
    if not outputs_dir.is_dir():
        return ()
    for root, dirnames, filenames in os.walk(outputs_dir, followlinks=False):
        root_path = Path(root)
        # Symlinked directories are recorded but never descended into.
        for dirname in dirnames:
            candidate = root_path / dirname
            metadata = candidate.lstat()
            if os.path.islink(candidate):
                entries.append(
                    RawOutputEntry(
                        relative_path=candidate.relative_to(outputs_dir).as_posix(),
                        sha256="",
                        size_bytes=metadata.st_size,
                        is_symlink=True,
                        is_regular=False,
                    )
                )
        for filename in filenames:
            candidate = root_path / filename
            metadata = candidate.lstat()
            relative = candidate.relative_to(outputs_dir).as_posix()
            if os.path.islink(candidate):
                entries.append(
                    RawOutputEntry(
                        relative_path=relative,
                        sha256="",
                        size_bytes=metadata.st_size,
                        is_symlink=True,
                        is_regular=False,
                    )
                )
                continue
            if os.path.isfile(candidate):
                try:
                    sha256 = hashlib.sha256(candidate.read_bytes()).hexdigest()
                except OSError:
                    sha256 = ""
                entries.append(
                    RawOutputEntry(
                        relative_path=relative,
                        sha256=sha256,
                        size_bytes=metadata.st_size,
                        is_symlink=False,
                        is_regular=True,
                    )
                )
            else:
                entries.append(
                    RawOutputEntry(
                        relative_path=relative,
                        sha256="",
                        size_bytes=metadata.st_size,
                        is_symlink=False,
                        is_regular=False,
                    )
                )
    return tuple(entries)


def _declared_outputs(manifest: Mapping[str, Any]) -> tuple[_DeclaredOutput, ...]:
    """Normalize the manifest's ``expected_outputs`` entries."""
    declared: list[_DeclaredOutput] = []
    raw_entries = manifest.get("expected_outputs") or []
    if not isinstance(raw_entries, list):
        return ()
    schema_keys = ("schema_uri", "schema_file", "schema")
    for index, entry in enumerate(raw_entries):
        if not isinstance(entry, Mapping):
            continue
        output_id = entry.get("output_id")
        output_id = str(output_id) if output_id is not None else f"#{index}"
        path_value = next(
            (entry[key] for key in _OUTPUT_PATH_KEYS if key in entry), None
        )
        if path_value is not None and not isinstance(path_value, str):
            path_value = None
        required_raw = entry.get("required", True)
        required = bool(required_raw) if isinstance(required_raw, bool) else True
        is_json = (
            isinstance(path_value, str) and path_value.lower().endswith(".json")
        ) or any(key in entry for key in schema_keys)
        fields_raw = entry.get("required_fields")
        required_fields = tuple(
            field
            for field in (fields_raw if isinstance(fields_raw, list) else ())
            if isinstance(field, str) and field
        )
        companions_raw = entry.get("companions")
        companions = tuple(
            companion
            for companion in (companions_raw if isinstance(companions_raw, list) else ())
            if isinstance(companion, str) and companion
        )
        declared.append(
            _DeclaredOutput(
                index=index,
                output_id=output_id,
                path_value=path_value,
                required=required,
                is_json=is_json,
                required_fields=required_fields,
                companions=companions,
            )
        )
    return tuple(declared)


def _declared_absolute_paths(
    outputs_dir: Path, root: Path, declared: tuple[_DeclaredOutput, ...]
) -> set[Path]:
    """Absolute, normalized paths of declared outputs and companions."""
    accepted: set[Path] = set()
    for item in declared:
        if item.path_value is None:
            continue
        candidate = (outputs_dir / item.path_value).resolve()
        if candidate.is_relative_to(root):
            accepted.add(candidate)
        for companion in item.companions:
            companion_path = (candidate.parent / companion).resolve()
            if companion_path.is_relative_to(root):
                accepted.add(companion_path)
    return accepted


def _method_identity_id(manifest: Mapping[str, Any]) -> str | None:
    """The method id recorded in the manifest, when one is declared."""
    method_identity = manifest.get("method_identity")
    if not isinstance(method_identity, Mapping):
        return None
    for key in ("method_id", "stable_id"):
        value = method_identity.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _expected_identity_values(manifest: Mapping[str, Any]) -> dict[str, str | None]:
    invocation_id = manifest.get("invocation_id")
    return {
        "run_id": invocation_id if isinstance(invocation_id, str) else None,
        "invocation_id": invocation_id if isinstance(invocation_id, str) else None,
        "method_id": _method_identity_id(manifest),
    }


def _parse_method_identity(manifest: Mapping[str, Any]) -> MethodIdentity | None:
    """Best-effort MethodIdentity from the manifest; None when unparseable.

    The manifest's ``method_identity`` is caller-supplied free JSON, so it
    may not match the harness's ``MethodIdentity`` shape (``stable_id``,
    integer ``version``, 64-hex ``definition_sha256``).  A manifest that
    cannot be parsed simply disables the method-identity sub-checks.
    """
    method_identity = manifest.get("method_identity")
    if not isinstance(method_identity, Mapping):
        return None
    try:
        return MethodIdentity(
            stable_id=str(method_identity.get("stable_id") or ""),
            version=int(method_identity.get("version")),
            definition_sha256=str(method_identity.get("definition_sha256") or ""),
        )
    except Exception:  # pragma: no cover — defensive, never raises
        return None


def _build_plan_from_manifest(manifest: Mapping[str, Any]) -> ResolvedPhasePlan:
    """Build a real ``ResolvedPhasePlan`` from manifest fields.

    The phase-specific validators dispatch on ``plan.identity.phase_id``
    and ``plan.mode_id``.  The manifest carries both ``phase`` and
    ``mode``, so we build the plan from those values instead of hardcoding
    an empty mode — the old shim caused spurious mode-mismatch failures
    on P3/P4 records and skipped mode-specific checks on P2/P5 records.
    """
    phase = manifest.get("phase", "")
    mode = manifest.get("mode", "")
    contract_version = manifest.get("phase_contract_version", "1.0.0")
    contract_sha256 = manifest.get("phase_contract_sha256", "0" * 64)
    # PhaseContractIdentity validates phase_id; default to P1 for empty/invalid.
    valid_phases = {"P1", "P2", "P3", "P4", "P5"}
    phase_id = str(phase) if phase in valid_phases else "P1"
    return ResolvedPhasePlan(
        identity=PhaseContractIdentity(
            phase_id=phase_id,
            contract_version=str(contract_version),
            phase_contract_sha256=str(contract_sha256),
        ),
        mode_id=str(mode) if mode else "",
        choice_values={},
        context_policy="",
        stages=(),
        output_contracts=(),
        prepared_contexts=(),
        validation_rules=(),
        publication_bindings=(),
        promotion={},
    )


def _parse_json_outputs(
    outputs_dir: Path,
    root: Path,
    declared: tuple[_DeclaredOutput, ...],
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Parse every declared JSON output once; share results across checks.

    Returns ``(documents, problems, details)`` where *documents* maps the
    declared output id to its parsed document (only when parse succeeded).
    """
    documents: dict[str, Any] = {}
    problems: list[str] = []
    details: list[str] = []
    for item in declared:
        if not item.is_json or item.path_value is None:
            continue
        resolved = (outputs_dir / item.path_value).resolve()
        if not resolved.is_relative_to(root):
            continue  # safe_paths/inventory already report the escape
        if resolved.is_symlink() or not resolved.is_file():
            continue  # inventory already reports the missing/non-regular output
        try:
            document = loads_json(resolved.read_bytes(), source=str(resolved))
        except JsonLoadError as error:
            problems.append(
                f"{item.output_id}: not strict JSON: {error.message}"
            )
            continue
        except OSError as error:
            problems.append(f"{item.output_id}: unreadable: {error}")
            continue
        documents[item.output_id] = document
        if item.required_fields:
            if type(document) is not dict:
                problems.append(
                    f"{item.output_id}: required fields declared but the output "
                    "is not a JSON object"
                )
                continue
            missing = [field for field in item.required_fields if field not in document]
            if missing:
                problems.append(
                    f"{item.output_id}: missing required field(s): "
                    + ", ".join(missing)
                )
            else:
                details.append(
                    f"{item.output_id}: required fields present: "
                    + ", ".join(item.required_fields)
                )
        else:
            details.append(
                f"{item.output_id}: no required_fields declared; "
                "field-level checks skipped"
            )
    return documents, problems, details


# --------------------------------------------------------------------------- #
# Checks                                                                       #
# --------------------------------------------------------------------------- #


def _check_inventory(
    outputs_dir: Path,
    root: Path,
    declared: tuple[_DeclaredOutput, ...],
    inventory: tuple[RawOutputEntry, ...],
) -> OutputValidationCheck:
    problems: list[str] = []
    declared_paths = _declared_absolute_paths(outputs_dir, root, declared)
    for item in declared:
        if item.path_value is None:
            continue
        resolved = (outputs_dir / item.path_value).resolve()
        if not resolved.is_relative_to(root):
            problems.append(
                f"{item.output_id}: declared path {item.path_value!r} does not "
                "resolve inside outputs/"
            )
            continue
        if resolved.is_symlink():
            problems.append(
                f"{item.output_id}: declared output is a symlink: "
                f"{item.path_value!r}"
            )
            continue
        if not resolved.is_file():
            problems.append(
                f"{item.output_id}: declared output is missing or not a "
                f"regular file: {item.path_value!r}"
            )
            continue
        if resolved.stat().st_size == 0:
            problems.append(
                f"{item.output_id}: declared output is empty: "
                f"{item.path_value!r}"
            )
    for entry in inventory:
        absolute = (outputs_dir / entry.relative_path).resolve()
        if absolute in declared_paths:
            continue
        if entry.is_symlink:
            problems.append(
                f"undeclared symlink in outputs/: {entry.relative_path}"
            )
        elif not entry.is_regular:
            problems.append(
                f"undeclared special entry in outputs/: {entry.relative_path}"
            )
        else:
            problems.append(f"undeclared file in outputs/: {entry.relative_path}")
    if problems:
        return _fail("inventory", _summarize(problems))
    return _pass(
        "inventory",
        f"{len(declared)} declared output(s) verified; "
        f"no undeclared files under outputs/",
    )


def _check_safe_paths(
    outputs_dir: Path, root: Path, declared: tuple[_DeclaredOutput, ...]
) -> OutputValidationCheck:
    problems: list[str] = []
    for item in declared:
        if item.path_value is None:
            continue
        raw = item.path_value
        if raw.startswith(("/", "\\")) or Path(raw).is_absolute():
            problems.append(f"{item.output_id}: absolute declared path: {raw!r}")
            continue
        if ".." in Path(raw).parts:
            problems.append(f"{item.output_id}: '..' escape in declared path: {raw!r}")
            continue
        resolved = (outputs_dir / raw).resolve()
        if not resolved.is_relative_to(root):
            problems.append(
                f"{item.output_id}: declared path escapes outputs/: {raw!r}"
            )
        for companion in item.companions:
            companion_path = (resolved.parent / companion).resolve()
            if not companion_path.is_relative_to(root):
                problems.append(
                    f"{item.output_id}: companion {companion!r} escapes outputs/"
                )
    if problems:
        return _fail("safe_paths", _summarize(problems))
    return _pass("safe_paths", "all declared output and companion paths stay inside outputs/")


def _check_schema(
    declared: tuple[_DeclaredOutput, ...],
    documents: dict[str, Any],
    problems: list[str],
    details: list[str],
) -> OutputValidationCheck:
    json_declared = sum(
        1 for item in declared if item.is_json and item.path_value is not None
    )
    if json_declared == 0:
        return _pass("schema", "no JSON outputs declared")
    if problems:
        return _fail("schema", _summarize(problems))
    return _pass("schema", "; ".join(details) or "all JSON outputs parse strictly")


def _check_nonempty_scientific_fields(
    declared: tuple[_DeclaredOutput, ...],
    documents: dict[str, Any],
) -> OutputValidationCheck:
    problems: list[str] = []
    checked = 0
    for item in declared:
        if not item.required_fields:
            continue
        document = documents.get(item.output_id)
        if type(document) is not dict:
            continue  # missing/parse failures are reported by other checks
        checked += 1
        for field in item.required_fields:
            if field not in document:
                continue  # missing fields are reported by the schema check
            value = document[field]
            if value is None:
                problems.append(
                    f"{item.output_id}: required field {field!r} is null"
                )
            elif value == "":
                problems.append(
                    f"{item.output_id}: required field {field!r} is an empty string"
                )
            elif value == []:
                problems.append(
                    f"{item.output_id}: required field {field!r} is an empty array"
                )
            elif value == {}:
                problems.append(
                    f"{item.output_id}: required field {field!r} is an empty object"
                )
    if checked == 0:
        return _pass(
            "nonempty_scientific_fields",
            "no declared required_fields to check",
        )
    if problems:
        return _fail("nonempty_scientific_fields", _summarize(problems))
    return _pass(
        "nonempty_scientific_fields",
        f"all declared required fields are nonempty across {checked} output(s)",
    )


def _check_companions(
    outputs_dir: Path, root: Path, declared: tuple[_DeclaredOutput, ...]
) -> OutputValidationCheck:
    problems: list[str] = []
    verified = 0
    for item in declared:
        if not item.companions or item.path_value is None:
            continue
        resolved = (outputs_dir / item.path_value).resolve()
        if (
            not resolved.is_relative_to(root)
            or resolved.is_symlink()
            or not resolved.is_file()
        ):
            problems.append(
                f"{item.output_id}: companions cannot be verified — the "
                "declared output is missing or not a regular file"
            )
            continue
        for companion in item.companions:
            companion_path = (resolved.parent / companion).resolve()
            if not companion_path.is_relative_to(root):
                problems.append(
                    f"{item.output_id}: companion {companion!r} escapes outputs/"
                )
                continue
            if companion_path.is_symlink():
                problems.append(
                    f"{item.output_id}: companion {companion!r} is a symlink"
                )
                continue
            if not companion_path.is_file():
                problems.append(
                    f"{item.output_id}: companion {companion!r} is missing"
                )
                continue
            if companion_path.stat().st_size == 0:
                problems.append(
                    f"{item.output_id}: companion {companion!r} is empty"
                )
                continue
            verified += 1
    if problems:
        return _fail("companions", _summarize(problems))
    if verified == 0:
        return _pass("companions", "no declared companions")
    return _pass("companions", f"{verified} declared companion(s) verified nonempty")


def _check_identity(
    manifest: Mapping[str, Any],
    documents: dict[str, Any],
) -> OutputValidationCheck:
    expected = _expected_identity_values(manifest)
    problems: list[str] = []
    details: list[str] = []
    verified = 0
    for output_id, document in sorted(documents.items()):
        if type(document) is not dict:
            continue
        for key in _IDENTITY_KEYS:
            if key not in document:
                continue
            want = expected.get(key)
            if want is None:
                details.append(
                    f"{output_id}: manifest declares no {key}; field not verified"
                )
                continue
            verified += 1
            if document[key] != want:
                problems.append(
                    f"{output_id}: {key} mismatch — output has "
                    f"{document[key]!r}, manifest has {want!r}"
                )
    if problems:
        return _fail("identity", _summarize(problems))
    if verified == 0:
        return _pass("identity", "no run/method identity fields in output JSONs")
    return _pass("identity", f"{verified} identity field(s) match the manifest basis")


def _check_phase_consistency(
    manifest: Mapping[str, Any],
    outputs_dir: Path,
    root: Path,
    declared: tuple[_DeclaredOutput, ...],
    documents: dict[str, Any],
    inventory: tuple[RawOutputEntry, ...],
) -> OutputValidationCheck:
    phase = manifest.get("phase")
    phase = str(phase) if isinstance(phase, str) and phase else "run"
    if phase not in _PHASE_VALIDATOR_PHASES:
        return _skip(
            "phase_consistency",
            f"no phase-specific validator for phase {phase!r}",
        )
    prefix = phase.lower() + "."
    candidate_ids = [
        output_id
        for output_id, document in documents.items()
        if output_id.startswith(prefix) and isinstance(document, (dict, list))
    ]
    if not candidate_ids:
        return _skip(
            "phase_consistency",
            f"no declared output ids match the phase contract id prefix "
            f"{prefix!r}; the phase validator cannot bind",
        )
    inventory_by_path = {entry.relative_path: entry for entry in inventory}
    outputs_map: dict[str, RegisteredValidatedOutput] = {}
    for item in declared:
        if (
            item.path_value is None
            or item.output_id not in candidate_ids
            or item.output_id not in documents
        ):
            continue
        document = documents[item.output_id]
        if not isinstance(document, (dict, list)):
            continue
        resolved = (outputs_dir / item.path_value).resolve()
        relative = resolved.relative_to(outputs_dir).as_posix()
        entry = inventory_by_path.get(relative)
        if entry is None or not entry.sha256:
            continue
        outputs_map[item.output_id] = RegisteredValidatedOutput(
            contract_output_id=item.output_id,
            document=document,
            artifact=RegisteredArtifactMetadata(
                artifact_id=item.output_id,
                sha256=entry.sha256,
                byte_length=entry.size_bytes,
                media_type="application/json",
                storage_uri=str(resolved),
            ),
        )
    if not outputs_map:
        return _skip(
            "phase_consistency",
            f"phase validator inputs could not be constructed for {phase}",
        )
    findings: list[Any] = []
    validate_phase_scientific(
        plan=_build_plan_from_manifest(manifest),
        outputs=outputs_map,
        selected_method=_parse_method_identity(manifest),
        findings=findings,
    )
    if findings:
        return _fail(
            "phase_consistency",
            _summarize(
                [f"{finding.code}: {finding.message}" for finding in findings]
            ),
        )
    return _pass(
        "phase_consistency",
        f"phase-specific validator for {phase} passed "
        f"({len(outputs_map)} output(s) bound)",
    )


def _summarize(problems: list[str]) -> str:
    shown = "; ".join(problems[:3])
    remainder = len(problems) - 3
    if remainder > 0:
        shown += f" ({remainder} more)"
    return shown


# --------------------------------------------------------------------------- #
# Entry point                                                                  #
# --------------------------------------------------------------------------- #


def validate_run_outputs(
    assembler: RunProfileAssembler,
    seal_or_invocation_id: SealedRun | str,
) -> OutputValidationReport:
    """Validate one closed launch's outputs against its sealed manifest.

    *seal_or_invocation_id* is a :class:`SealedRun` or an invocation id
    resolved through the seal registry (manifest digest verified).  The
    invocation must have a terminal launch record — a ``running`` launch
    (or no launch at all) raises :class:`LaunchNotClosedError` before any
    output byte is read.

    The raw-output inventory (file list, sha256, sizes under ``outputs/``)
    is captured before any judgment.  The report's verdict and full JSON
    are recorded into ``run_validation_reports``; nothing else is written.
    """
    sealed = _resolve_seal(assembler, seal_or_invocation_id)
    launch = _require_terminal_launch(assembler, sealed.invocation_id)

    outputs_dir = sealed.run_dir / "outputs"
    root = outputs_dir.resolve()
    inventory = _walk_raw_inventory(outputs_dir)
    declared = _declared_outputs(sealed.manifest)

    documents, schema_problems, schema_details = _parse_json_outputs(
        outputs_dir, root, declared
    )

    checks = (
        _check_inventory(outputs_dir, root, declared, inventory),
        _check_safe_paths(outputs_dir, root, declared),
        _check_schema(declared, documents, schema_problems, schema_details),
        _check_nonempty_scientific_fields(declared, documents),
        _check_companions(outputs_dir, root, declared),
        _check_identity(sealed.manifest, documents),
        _check_phase_consistency(
            sealed.manifest, outputs_dir, root, declared, documents, inventory
        ),
    )

    digests = {
        entry.relative_path: entry.sha256
        for entry in inventory
        if entry.sha256
    }
    report = OutputValidationReport(
        launch_id=launch["launch_id"],
        seal_id=sealed.seal_id,
        invocation_id=sealed.invocation_id,
        project_id=sealed.project_id,
        phase=str(sealed.manifest.get("phase") or "run"),
        role=sealed.role,
        validated_at=isoformat_utc(utc_now()),
        raw_inventory=inventory,
        checks=checks,
        digests=digests,
    )
    assembler.store.record_validation_report(
        launch_id=launch["launch_id"],
        invocation_id=sealed.invocation_id,
        seal_id=sealed.seal_id,
        verdict=report.verdict,
        report_json=json.dumps(report.to_dict(), indent=2, sort_keys=True),
        validated_at=report.validated_at,
    )
    return report


__all__ = [
    "FAIL",
    "LaunchNotClosedError",
    "OutputValidationCheck",
    "OutputValidationError",
    "OutputValidationReport",
    "PASS",
    "REPORT_FORMAT",
    "REPORT_FORMAT_VERSION",
    "RawOutputEntry",
    "SKIPPED",
    "validate_run_outputs",
]
