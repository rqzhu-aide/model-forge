"""Atomic method activation, retirement, and reactivation control transactions."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, utc_now
from ..specification import SpecificationPackage
from ..storage.artifacts import ArtifactStore
from ..storage.repository import HubRepository
from .ids import new_id
from .repository_views import row_json


class MethodLifecycleCommandService:
    """Replace one method and the Phase 2 catalog without starting a run."""

    def __init__(
        self,
        repository: HubRepository,
        artifacts: ArtifactStore,
        specification: SpecificationPackage,
    ) -> None:
        self.repository = repository
        self.artifacts = artifacts
        self.specification = specification

    def change(
        self,
        project_id: str,
        method_id: str,
        *,
        target_state: str,
        reason: str,
        command_id: str,
        command_sha256: str,
        requested_by: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if target_state not in {"active", "retired"}:
            raise ValueError("Method lifecycle target must be active or retired.")

        method_row = self.repository.get_current_record(
            project_id, f"methods/{method_id}/current"
        )
        catalog_row = self.repository.get_current_record(
            project_id, "p2.method_catalog.current"
        )
        if method_row is None or method_row["record_type"] != "method_record":
            raise ValueError("The selected method has no current formal method record.")
        if catalog_row is None or catalog_row["record_type"] != "method_catalog":
            raise ValueError("The project has no current formal method catalog.")

        prior_method = row_json(method_row)
        identity = prior_method.get("identity")
        if type(identity) is not dict or identity.get("stable_id") != method_id:
            raise ValueError("The selected method does not match its current formal slot.")
        prior_state = str(prior_method.get("lifecycle_state", "proposed"))
        legal = {
            ("active", "retired"),
            ("retired", "active"),
            ("proposed", "active"),
        }
        if (prior_state, target_state) not in legal:
            if prior_state == target_state:
                raise ValueError("The method is already in the requested lifecycle state.")
            raise ValueError(
                "Only proposed methods may be activated, active methods retired, "
                "and retired methods reactivated."
            )

        prior_catalog = row_json(catalog_row)
        methods = prior_catalog.get("methods")
        if type(methods) is not list:
            raise ValueError("The current method catalog has no structured method list.")
        matching = [
            item
            for item in methods
            if type(item) is dict
            and type(item.get("identity")) is dict
            and item["identity"].get("stable_id") == method_id
        ]
        if len(matching) != 1:
            raise ValueError(
                "The current method catalog does not identify exactly one selected method."
            )
        if matching[0].get("identity") != identity:
            raise ValueError("The method catalog and current method identity disagree.")
        if str(matching[0].get("lifecycle_state", "proposed")) != prior_state:
            raise ValueError("The method catalog and current lifecycle state disagree.")

        at = now or utc_now()
        timestamp = isoformat_utc(at)
        receipt_id = new_id("receipt", "method_lifecycle")
        method_generation_id = new_id("generation", f"{method_id}_lifecycle")
        catalog_generation_id = new_id("generation", "method_catalog")

        method = dict(prior_method)
        method.update(
            {
                "generation_id": method_generation_id,
                "lifecycle_state": target_state,
                "lineage": {
                    "predecessor": dict(identity),
                    "change_class": "lifecycle",
                    "change_summary": reason.strip(),
                    "predecessor_generation_id": str(method_row["generation_id"]),
                    "change_source": {
                        "kind": "method_lifecycle_command",
                        "command_id": command_id,
                        "command_sha256": command_sha256,
                    },
                },
                "updated_at": timestamp,
                "published_at": timestamp,
                "publication_receipt_id": receipt_id,
            }
        )
        method_sha = self.specification.digests.compute("method_record.content", method)
        method["content_sha256"] = method_sha
        self.specification.schemas.require_valid("method.schema.json", method)
        self.specification.digests.require_match("method_record.content", method)

        catalog_methods = [
            method if item is matching[0] else dict(item)
            for item in methods
        ]
        catalog = dict(prior_catalog)
        catalog["methods"] = catalog_methods
        catalog["method_count"] = len(catalog_methods)
        catalog["active_method_count"] = sum(
            str(item.get("lifecycle_state", "proposed")) != "retired"
            for item in catalog_methods
        )
        projections = catalog.get("projections")
        if type(projections) is list:
            catalog["projections"] = [
                {
                    **dict(item),
                    "lifecycle_state": target_state,
                }
                if type(item) is dict
                and type(item.get("identity")) is dict
                and item["identity"].get("stable_id") == method_id
                else dict(item)
                for item in projections
                if type(item) is dict
            ]
        catalog["updated_at"] = timestamp
        catalog["publication_receipt_id"] = receipt_id
        catalog["supersedes_generation_id"] = str(catalog_row["generation_id"])
        catalog.pop("content_sha256", None)
        catalog_sha = hashlib.sha256(canonicalize(catalog)).hexdigest()
        catalog["content_sha256"] = catalog_sha

        method_artifact_id = self._record_artifact(
            project_id,
            "method_lifecycle",
            method,
            command_id=command_id,
            recorded_at=at,
        )
        catalog_artifact_id = self._record_artifact(
            project_id,
            "method_catalog_lifecycle",
            catalog,
            command_id=command_id,
            recorded_at=at,
        )

        project = self.repository.get_project(project_id)
        prior_sequence = int(project["authority_sequence"])
        prior_root = str(project["authority_root_sha256"])
        prior_revision = int(project["current_revision"])
        events = [
            self._event(
                project_id,
                "formal_generation_published",
                method_generation_id,
                f"methods/{method_id}/current",
                method_sha,
                command_id,
                timestamp,
            ),
            self._event(
                project_id,
                "formal_generation_superseded",
                str(method_row["generation_id"]),
                f"methods/{method_id}/current",
                str(method_row["content_sha256"]),
                command_id,
                timestamp,
                replacement_generation_id=method_generation_id,
            ),
            self._event(
                project_id,
                "formal_generation_published",
                catalog_generation_id,
                "p2.method_catalog.current",
                catalog_sha,
                command_id,
                timestamp,
            ),
            self._event(
                project_id,
                "formal_generation_superseded",
                str(catalog_row["generation_id"]),
                "p2.method_catalog.current",
                str(catalog_row["content_sha256"]),
                command_id,
                timestamp,
                replacement_generation_id=catalog_generation_id,
            ),
        ]
        event_entries: list[tuple[dict[str, Any], str, str]] = []
        authority_root = prior_root
        for event in events:
            event_sha = hashlib.sha256(canonicalize(event)).hexdigest()
            authority_root = hashlib.sha256(
                bytes.fromhex(authority_root) + bytes.fromhex(event_sha)
            ).hexdigest()
            event_entries.append((event, event_sha, authority_root))

        receipt = {
            "schema_version": "1.0.0",
            "receipt_id": receipt_id,
            "project_id": project_id,
            "source": {
                "kind": "method_lifecycle_command",
                "command_id": command_id,
                "command_sha256": command_sha256,
            },
            "record_changes": [
                {
                    "record_type": "method_record",
                    "prior_generation_id": str(method_row["generation_id"]),
                    "new_generation_id": method_generation_id,
                },
                {
                    "record_type": "method_catalog",
                    "prior_generation_id": str(catalog_row["generation_id"]),
                    "new_generation_id": catalog_generation_id,
                },
            ],
            "target_lifecycle_state": target_state,
            "reason": reason.strip(),
            "requested_by": requested_by,
            "authority_event_ids": [str(item["event_id"]) for item in events],
            "prior_authority_sequence": prior_sequence,
            "new_authority_sequence": prior_sequence + len(events),
            "prior_authority_root_sha256": prior_root,
            "new_authority_root_sha256": authority_root,
            "prior_current_revision": prior_revision,
            "new_current_revision": prior_revision + 1,
            "atomic": True,
            "committed_at": timestamp,
        }
        receipt_sha = hashlib.sha256(canonicalize(receipt)).hexdigest()

        with self.repository.publication_transaction(
            project_id,
            receipt_id,
            prior_sequence,
            prior_root,
            expected_current_revision=prior_revision,
        ) as publication:
            publication.add_formal_generation(
                method_generation_id,
                "method_record",
                method_artifact_id,
                method_sha,
                method,
                logical_slot=f"methods/{method_id}/current",
                supersedes_generation_id=str(method_row["generation_id"]),
                published_at=at,
            )
            publication.add_formal_generation(
                catalog_generation_id,
                "method_catalog",
                catalog_artifact_id,
                catalog_sha,
                catalog,
                logical_slot="p2.method_catalog.current",
                supersedes_generation_id=str(catalog_row["generation_id"]),
                published_at=at,
            )
            publication.replace_current_slot(
                f"methods/{method_id}/current",
                method_generation_id,
                expected_generation_id=str(method_row["generation_id"]),
                updated_at=at,
            )
            publication.replace_current_slot(
                "p2.method_catalog.current",
                catalog_generation_id,
                expected_generation_id=str(catalog_row["generation_id"]),
                updated_at=at,
            )
            for event, event_sha, event_root in event_entries:
                publication.append_authority_event(
                    str(event["event_id"]),
                    str(event["event_type"]),
                    event_sha,
                    event_root,
                    event,
                    committed_at=at,
                )
            publication.record_receipt(
                receipt_sha,
                receipt,
                command_id=command_id,
                committed_at=at,
            )
        return {
            "receipt_id": receipt_id,
            "method_generation_id": method_generation_id,
            "catalog_generation_id": catalog_generation_id,
            "target_lifecycle_state": target_state,
        }

    def _record_artifact(
        self,
        project_id: str,
        purpose: str,
        document: dict[str, Any],
        *,
        command_id: str,
        recorded_at: datetime,
    ) -> str:
        payload = (
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        stored = self.artifacts.put_bytes(payload)
        artifact_id = new_id("artifact", purpose)
        self.repository.record_artifact(
            artifact_id,
            project_id,
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "relative_path": stored.relative_path,
                "purpose": purpose,
                "source_command_id": command_id,
            },
            recorded_at=recorded_at,
        )
        return artifact_id

    @staticmethod
    def _event(
        project_id: str,
        event_type: str,
        generation_id: str,
        logical_slot: str,
        content_sha256: str,
        command_id: str,
        committed_at: str,
        *,
        replacement_generation_id: str | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": new_id("authority_event", event_type),
            "event_type": event_type,
            "project_id": project_id,
            "generation_id": generation_id,
            "logical_slot": logical_slot,
            "content_sha256": content_sha256,
            "source_command_id": command_id,
            "committed_at": committed_at,
        }
        if replacement_generation_id is not None:
            event["replacement_generation_id"] = replacement_generation_id
        return event


__all__ = ["MethodLifecycleCommandService"]
