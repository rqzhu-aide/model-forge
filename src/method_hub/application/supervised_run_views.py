"""WP-F0 read projections over the run-seal store's durable records.

This module is the read surface for the supervised-run machinery: every
value it emits comes from durable state — the seal registry, launch,
validation, and promotion tables (all via :class:`RunSealStore` read
methods) or the stored, digest-verified manifest JSON document written
at seal time.  No file-existence inference is used to decide what
happened, and nothing here writes.

The store offers no per-invocation promotion listing yet, so the
invocation's promotion records are selected from the project-role
promotion set the store returns; the bound is far beyond any realistic
count and keeps this read layer off the WP-D/E modules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..api.models import (
    SupervisedLaunchRecord,
    SupervisedManifestSummary,
    SupervisedPromotionRecord,
    SupervisedRunDetail,
    SupervisedRunSummary,
    SupervisedValidationReport,
)
from ..digests.jcs import canonicalize
from .run_profile_assembler import RunSealStore

#: Upper bound for project-scoped store listings the read layer composes
#: into per-invocation views.  The store's list helpers default to 50
#: rows; an invocation's own records are always a small subset of its
#: project-role's records, so this bound is generous without being open
#: ended.
_READ_LIMIT = 1000

#: WP-D2b (``run_preflight``) reports in memory only — it never persists
#: the report, and the launch flow consumes it solely to abort.  There is
#: therefore no durable preflight report to surface; the detail view
#: carries this note instead of a report.
PREFLIGHT_NOT_PERSISTED_NOTE = (
    "Preflight reports are not persisted (WP-D2b runs read-only and never "
    "writes its report); no preflight data is available."
)


def read_manifest_document(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """Load and digest-verify the stored manifest JSON for one seal row.

    The manifest path comes from the seal registry (``run_dir``) and the
    document is accepted only when its JCS digest still matches the
    registry's immutable ``manifest_sha256``.  Returns ``None`` when the
    document is unreadable or fails verification (for example after
    WP-E3 retention pruned the run directory).
    """
    manifest_path = Path(str(record["run_dir"])) / "manifest" / "manifest.json"
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    if hashlib.sha256(canonicalize(document)).hexdigest() != record["manifest_sha256"]:
        return None
    if not all(isinstance(document.get(key), str) for key in ("project_id", "role", "phase", "sealed_at")):
        return None
    if not isinstance(document.get("expected_outputs"), list):
        return None
    if not isinstance(document.get("role_definition"), dict):
        return None
    return document


def supervised_run_summary(
    record: Mapping[str, Any], store: RunSealStore
) -> SupervisedRunSummary:
    """Condense one seal registry row into a list-view summary (WP-F0)."""
    manifest = read_manifest_document(record)
    launches = store.list_launch_records_by_invocation(str(record["invocation_id"]))
    latest_launch = launches[-1] if launches else None
    validation = _latest_validation_report(store, launches)
    memory_snapshot = manifest.get("memory_snapshot") if manifest is not None else None
    return SupervisedRunSummary(
        invocation_id=str(record["invocation_id"]),
        seal_id=str(record["seal_id"]),
        role=str(record["role"]),
        phase=str(manifest["phase"]) if manifest is not None else None,
        method_identity=manifest.get("method_identity") if manifest is not None else None,
        memory_policy=(
            str(memory_snapshot["policy"])
            if isinstance(memory_snapshot, dict) and isinstance(memory_snapshot.get("policy"), str)
            else None
        ),
        sealed_at=str(record["sealed_at"]),
        latest_launch_status=(
            str(latest_launch["status"]) if latest_launch is not None else None
        ),
        validation_verdict=(
            str(validation["verdict"]) if validation is not None else None
        ),
        promoted=store.find_promotion_record_by_invocation(
            str(record["invocation_id"])
        )
        is not None,
    )


def supervised_run_detail(
    record: Mapping[str, Any], store: RunSealStore
) -> SupervisedRunDetail:
    """Assemble the complete durable read view of one invocation (WP-F0)."""
    manifest = read_manifest_document(record)
    launches = store.list_launch_records_by_invocation(str(record["invocation_id"]))
    validation = _latest_validation_report(store, launches)
    promotions = [
        row
        for row in store.list_promotion_records(
            project_id=str(record["project_id"]),
            role=str(record["role"]),
            limit=_READ_LIMIT,
        )
        if str(row["invocation_id"]) == str(record["invocation_id"])
    ]
    # The store returns promotions newest-first; report them
    # chronologically, matching the launch records.
    promotions.reverse()
    return SupervisedRunDetail(
        invocation_id=str(record["invocation_id"]),
        seal_id=str(record["seal_id"]),
        project_id=str(record["project_id"]),
        role=str(record["role"]),
        sealed_at=str(record["sealed_at"]),
        manifest=(
            _manifest_summary(record, manifest) if manifest is not None else None
        ),
        manifest_note=(
            None
            if manifest is not None
            else (
                "The stored manifest JSON is unreadable or fails digest "
                "verification (for example after WP-E3 retention pruned "
                "the run directory)."
            )
        ),
        preflight_report=None,
        preflight_note=PREFLIGHT_NOT_PERSISTED_NOTE,
        launches=[_launch_view(row) for row in launches],
        validation=(
            _validation_view(validation) if validation is not None else None
        ),
        promotions=[_promotion_view(row) for row in promotions],
    )


def _latest_validation_report(
    store: RunSealStore, launches: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return the newest stored validation report across all launches.

    ``launches`` are oldest-first, so the newest launch is scanned
    first; re-validation replaces the report on its launch row, and the
    most recently validated launch is the latest evidence.
    """
    for launch in reversed(launches):
        report = store.get_validation_report(str(launch["launch_id"]))
        if report is not None:
            return report
    return None


def _manifest_summary(
    record: Mapping[str, Any], manifest: Mapping[str, Any]
) -> SupervisedManifestSummary:
    role_definition = manifest["role_definition"]
    asset_digests = role_definition.get("asset_digests")
    return SupervisedManifestSummary(
        project_id=str(manifest["project_id"]),
        role=str(manifest["role"]),
        phase=str(manifest["phase"]),
        method_identity=manifest.get("method_identity"),
        memory_snapshot=manifest.get("memory_snapshot"),
        session_snapshot=manifest.get("session_snapshot"),
        expected_outputs=list(manifest["expected_outputs"]),
        hermes=manifest.get("hermes"),
        role_asset_digests={
            str(key): str(value)
            for key, value in (
                asset_digests.items() if isinstance(asset_digests, dict) else {}
            )
        },
        sealed_at=str(manifest["sealed_at"]),
    )


def _launch_view(row: Mapping[str, Any]) -> SupervisedLaunchRecord:
    return SupervisedLaunchRecord(
        launch_id=str(row["launch_id"]),
        status=str(row["status"]),
        exit_code=row["exit_code"] if row["exit_code"] is not None else None,
        external_execution_id=_optional_str(row["external_execution_id"]),
        task_brief_sha256=_optional_str(row["task_brief_sha256"]),
        launched_at=str(row["launched_at"]),
        closed_at=_optional_str(row["closed_at"]),
    )


def _validation_view(row: Mapping[str, Any]) -> SupervisedValidationReport:
    checks: list[dict[str, str]] = []
    try:
        document = json.loads(str(row["report_json"]))
    except ValueError:
        document = None
    if isinstance(document, dict) and isinstance(document.get("checks"), list):
        checks = [
            {
                "name": str(check.get("name")),
                "status": str(check.get("status")),
                "detail": str(check.get("detail")),
            }
            for check in document["checks"]
            if isinstance(check, dict)
        ]
    return SupervisedValidationReport(
        launch_id=str(row["launch_id"]),
        verdict=str(row["verdict"]),
        validated_at=str(row["validated_at"]),
        checks=checks,
    )


def _promotion_view(row: Mapping[str, Any]) -> SupervisedPromotionRecord:
    return SupervisedPromotionRecord(
        record_id=str(row["record_id"]),
        promoted_at=str(row["promoted_at"]),
        status=str(row["status"]),
        before_digest=_json_document(row["before_digest"]),
        after_digest=_json_document(row["after_digest"]),
        backup_paths=_json_document(row["backup_paths"]),
    )


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _json_document(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str):
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


__all__ = [
    "PREFLIGHT_NOT_PERSISTED_NOTE",
    "read_manifest_document",
    "supervised_run_detail",
    "supervised_run_summary",
]
