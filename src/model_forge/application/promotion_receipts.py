"""Promotion receipts (Block 5, WP-E3).

:func:`write_promotion_receipt` composes one compact, immutable JSON
receipt per successful promotion into
``run_dir/manifest/promotion-receipt.json`` plus a JCS-canonicalized
SHA-256 sidecar (``promotion-receipt.sha256``).  The receipt binds the
WP-E2 promotion outcome (per-target before/after digests, backup
locations) to the WP-E1 validation report (verdict + validated output
digests) and to the input snapshot identity recorded in the immutable
manifest (memory identity, session sha256).  Writing is deterministic
and idempotent: a second call returns the existing receipt path without
rewriting anything.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from ..digests.jcs import canonicalize
from .run_profile_assembler import RunProfileAssembler
from .state_promotion import PromotionResult

RECEIPT_FORMAT = "model-forge.promotion-receipt"
RECEIPT_FORMAT_VERSION = "1.0.0"
RECEIPT_FILE_NAME = "promotion-receipt.json"
RECEIPT_DIGEST_FILE_NAME = "promotion-receipt.sha256"


class PromotionReceiptError(RuntimeError):
    """A promotion receipt could not be composed or written."""


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f".{path.name}.write-{os.urandom(4).hex()}"
    staging.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(staging, path)


def write_promotion_receipt(
    assembler: RunProfileAssembler,
    promotion_result: PromotionResult,
) -> Path:
    """Compose and write the immutable receipt for one promotion.

    Idempotent: an existing receipt is returned untouched (the document
    is fully deterministic, so a rewrite would be byte identical).  The
    sidecar holds SHA-256 of the RFC 8785 canonicalized document.
    """
    seal_record = assembler.store.find_by_invocation_id(
        promotion_result.invocation_id
    )
    if seal_record is None:
        raise PromotionReceiptError(
            f"No seal record for invocation {promotion_result.invocation_id!r}."
        )
    sealed = assembler._reconstruct(seal_record)  # noqa: SLF001 — verifies digest

    receipt_path = sealed.run_dir / "manifest" / RECEIPT_FILE_NAME
    if receipt_path.exists():
        return receipt_path

    launch = assembler.store.find_launch_record_by_invocation(
        sealed.invocation_id
    )
    if launch is None:
        raise PromotionReceiptError(
            f"No launch record for invocation {sealed.invocation_id!r}."
        )
    report_row = assembler.store.get_validation_report(launch["launch_id"])
    if report_row is None:
        raise PromotionReceiptError(
            f"No WP-E1 validation report for launch {launch['launch_id']!r}."
        )
    try:
        report_doc = json.loads(report_row["report_json"])
    except ValueError as error:
        raise PromotionReceiptError(
            "The stored validation report is not valid JSON."
        ) from error

    manifest = sealed.manifest
    memory_snapshot = manifest.get("memory_snapshot") or {}
    session_snapshot = manifest.get("session_snapshot") or {}

    document = {
        "format": RECEIPT_FORMAT,
        "format_version": RECEIPT_FORMAT_VERSION,
        "seal_id": promotion_result.seal_id,
        "invocation_id": promotion_result.invocation_id,
        "project_id": promotion_result.project_id,
        "role": promotion_result.role,
        "phase": str(manifest.get("phase") or "run"),
        "input_snapshot": {
            "memory_identity": memory_snapshot.get("identity"),
            "session_sha256": session_snapshot.get("sha256"),
        },
        "validation": {
            "verdict": report_row["verdict"],
            "launch_id": launch["launch_id"],
            "validated_at": report_row["validated_at"],
            "output_digests": dict(report_doc.get("digests") or {}),
        },
        "promoted_state": [
            {
                "target": target.name,
                "before_digest": target.before_digest,
                "after_digest": target.after_digest,
            }
            for target in promotion_result.targets
        ],
        "previous_current_state": {
            target.name: target.before_digest
            for target in promotion_result.targets
        },
        "backup_locations": {
            target.name: target.backup_path
            for target in promotion_result.targets
        },
        "promoted_at": promotion_result.promoted_at,
    }
    digest = hashlib.sha256(canonicalize(document)).hexdigest()
    _write_json_atomic(receipt_path, document)
    digest_path = receipt_path.with_name(RECEIPT_DIGEST_FILE_NAME)
    digest_path.write_text(digest + "\n", encoding="utf-8")
    return receipt_path


__all__ = [
    "RECEIPT_DIGEST_FILE_NAME",
    "RECEIPT_FILE_NAME",
    "RECEIPT_FORMAT",
    "RECEIPT_FORMAT_VERSION",
    "PromotionReceiptError",
    "write_promotion_receipt",
]
