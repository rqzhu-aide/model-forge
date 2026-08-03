"""Normative RunCommand construction from authenticated resolved user intent."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..application.ids import new_id
from ..domain.runs import RunRequest, isoformat_utc, thaw_json, utc_now
from ..specification import SpecificationPackage


def build_run_command(
    request: RunRequest,
    specification: SpecificationPackage,
    *,
    requested_at: datetime | None = None,
    command_id: str | None = None,
    sealed_basis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve and seal one exact command accepted from the researcher."""

    specification.resolve_phase(
        request.phase_contract,
        str(request.mode),
        thaw_json(request.choice_values),
        request.context_policy,
    )
    identity = request.phase_contract
    document: dict[str, Any] = {
        "schema_version": "1.0.0",
        "command_id": command_id or new_id("command", identity.phase_id.lower()),
        "idempotency_key": request.idempotency_key,
        "project_id": str(request.project_id),
        "phase": identity.phase_id,
        "phase_contract_version": str(identity.contract_version),
        "phase_contract_sha256": str(identity.phase_contract_sha256),
        "mode": str(request.mode),
        "choice_values": thaw_json(request.choice_values),
        "requested_by": {
            "user_id": str(request.user_id),
            "operating_actor_type": "user",
        },
        "context_policy": request.context_policy,
        "selected_current_input_ids": list(request.selected_current_input_ids),
        "resource_constraints": {
            "wall_time_limit_seconds": request.wall_time_limit_seconds,
            "network_policy": request.network_policy,
        },
        "content_sha256": "0" * 64,
        "requested_at": isoformat_utc(requested_at or utc_now()),
    }
    if sealed_basis is not None:
        document["sealed_basis"] = sealed_basis
    document["content_sha256"] = specification.digests.compute(
        "run_command.content", document
    )
    specification.schemas.require_valid("run-command.schema.json", document)
    specification.digests.require_match("run_command.content", document)
    return document


__all__ = ["build_run_command"]
