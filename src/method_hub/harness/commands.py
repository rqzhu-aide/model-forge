"""Normative RunCommand construction from authenticated resolved user intent."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..application.ids import new_id
from ..domain.identities import MethodIdentity
from ..domain.runs import RunRequest, isoformat_utc, thaw_json, utc_now
from ..specification import SpecificationPackage


def require_complete_sealed_basis(
    *,
    sealed_basis: dict[str, Any] | None,
    phase_roles: set[str],
    required_input_ids: set[str],
    selected_input_ids: set[str],
    expected_method: MethodIdentity | None = None,
) -> None:
    """Reject an underspecified reviewed basis at command acceptance time.

    This is the NEW-command acceptance gate for the reviewed-basis seal.
    ``sealed_basis`` stays optional in the schema (C2/C6) so that stored
    pre-upgrade commands still revalidate during restart recovery, but a
    command accepted from this point on must seal a complete basis: the
    authority head, the generation and artifact digest of every current
    input the run will consume, the exact method identity when the run is
    method-bound, and role resources for every role the phase requires.

    Raises ``ValueError`` with a message naming the missing component; the
    application service converts it into the stable STALE_BASIS rejection.
    """
    if sealed_basis is None:
        raise ValueError(
            "The reviewed basis is missing: this run action carries no "
            "descriptor basis to seal."
        )

    # 1. Authority head triple.
    head = sealed_basis.get("authority_head")
    if type(head) is not dict:
        raise ValueError("The reviewed basis is missing the authority head.")
    for key in ("authority_sequence", "authority_root_sha256", "current_revision"):
        if head.get(key) is None:
            raise ValueError(
                f"The reviewed basis is missing the authority head field {key!r}."
            )

    # 2. Input generations and digests for every input this run consumes.
    reviewed = sealed_basis.get("reviewed_current_inputs")
    if type(reviewed) is not list:
        raise ValueError("The reviewed basis is missing the reviewed current inputs.")
    sealed_by_option: dict[str, dict[str, Any]] = {}
    for entry in reviewed:
        option_id = entry.get("option_id") if type(entry) is dict else None
        if option_id is not None:
            sealed_by_option[str(option_id)] = entry
    needed = set(required_input_ids) | set(selected_input_ids)
    for input_id in sorted(needed):
        entry = sealed_by_option.get(input_id)
        if entry is None:
            raise ValueError(
                f"The reviewed basis does not seal current input {input_id!r} "
                "that this run requires."
            )
        if entry.get("generation_id") is None or entry.get("sha256") is None:
            raise ValueError(
                f"The reviewed basis seals current input {input_id!r} without "
                "its generation and artifact digest."
            )

    # 3. Method identity: the run must execute exactly the reviewed method.
    sealed_method = sealed_basis.get("method_identity")
    if expected_method is not None:
        if type(sealed_method) is not dict:
            raise ValueError(
                "The reviewed basis does not seal the submitted method identity."
            )
        expected = expected_method.to_dict()
        for key in ("stable_id", "version", "definition_sha256"):
            if sealed_method.get(key) != expected[key]:
                raise ValueError(
                    "The method identity in the reviewed basis does not match "
                    "the submitted method."
                )

    # 4. Role resources for every role the phase requires.
    resources = sealed_basis.get("role_resources")
    if type(resources) is not dict or not resources:
        raise ValueError(
            "The reviewed basis carries no role resources for the roles this "
            "phase requires."
        )
    for role in sorted(phase_roles):
        sealed_role = resources.get(role)
        if type(sealed_role) is not dict:
            raise ValueError(
                f"The reviewed basis omits role resources for role {role!r}."
            )
        for field in ("profile", "profile_version", "soul_sha256"):
            if not sealed_role.get(field):
                raise ValueError(
                    f"The reviewed basis underspecifies role {role!r}: "
                    f"missing {field}."
                )
        skills = sealed_role.get("skills")
        if type(skills) is not list:
            raise ValueError(
                f"The reviewed basis underspecifies role {role!r}: missing skills."
            )
        for skill in skills:
            if (
                type(skill) is not dict
                or not skill.get("skill_id")
                or not skill.get("bundle_sha256")
            ):
                raise ValueError(
                    f"The reviewed basis underspecifies role {role!r}: a skill "
                    "entry lacks its skill_id or bundle digest."
                )

        # WP-H2: the exact installed role configuration. The memory policy is
        # always declared by the WP-C base configuration, so it must be sealed
        # non-empty. model/provider/tools and the per-role phase instruction
        # are recorded as explicit nulls when the WP-C definition or phase
        # contract declares nothing -- the key must still be sealed so the
        # record is honest and the value is pinned for drift detection.
        for field in ("model", "provider", "phase_instruction", "tools"):
            if field not in sealed_role:
                raise ValueError(
                    f"The reviewed basis underspecifies role {role!r}: "
                    f"missing {field}."
                )
        if not sealed_role.get("memory_policy"):
            raise ValueError(
                f"The reviewed basis underspecifies role {role!r}: "
                "missing memory policy."
            )
        base_configuration = sealed_role.get("base_configuration")
        if (
            type(base_configuration) is not dict
            or not base_configuration.get("file_name")
            or not base_configuration.get("sha256")
        ):
            raise ValueError(
                f"The reviewed basis underspecifies role {role!r}: "
                "the base configuration lacks its content digest."
            )
        library_guidance = sealed_role.get("library_guidance")
        if (
            type(library_guidance) is not dict
            or not library_guidance.get("file_name")
            or not library_guidance.get("sha256")
        ):
            raise ValueError(
                f"The reviewed basis underspecifies role {role!r}: "
                "the library guidance lacks its content digest."
            )
        if type(sealed_role.get("custom_skills")) is not list:
            raise ValueError(
                f"The reviewed basis underspecifies role {role!r}: "
                "missing custom skills."
            )


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


__all__ = ["build_run_command", "require_complete_sealed_basis"]
