"""Project creation and its initial formal research brief."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from ..api.models import CreateProjectRequest, UpdateProjectBriefRequest
from ..digests.jcs import canonicalize
from ..domain.runs import isoformat_utc, utc_now
from ..storage.artifacts import ArtifactStore
from ..storage.repository import HubRepository, ZERO_SHA256
from .ids import new_id


class ProjectCommandService:
    def __init__(self, repository: HubRepository, artifacts: ArtifactStore) -> None:
        self.repository = repository
        self.artifacts = artifacts

    def create(
        self,
        command: CreateProjectRequest,
        *,
        owner_user_id: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Create a project and atomically establish its formal current brief."""

        at = now or utc_now()
        timestamp = isoformat_utc(at)
        project_id = new_id("project", command.name)
        payload = {
            "project_id": project_id,
            "name": command.name.strip(),
            "research_question": command.research_question.strip(),
            "domains": list(command.domains),
            "intended_use": command.intended_use.strip(),
            "scope": _optional_text(command.scope),
            "decision_criteria": _text_items(command.decision_criteria),
            "constraints": _text_items(command.constraints),
            "owner_user_id": owner_user_id,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        self.repository.create_project(project_id, payload, created_at=at)

        brief = {
            "schema_version": "1.0.0",
            "record_id": new_id("record", "project_brief"),
            "record_type": "project_brief",
            "project_id": project_id,
            "research_question": command.research_question.strip(),
            "domains": list(command.domains),
            "intended_use": command.intended_use.strip(),
            "scope": _optional_text(command.scope),
            "decision_criteria": _text_items(command.decision_criteria),
            "constraints": _text_items(command.constraints),
            "scope_note": "This brief is replaced only by an explicit project-scope command.",
            "created_at": timestamp,
        }
        bytes_payload = (
            json.dumps(brief, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode("utf-8")
        stored = self.artifacts.put_bytes(bytes_payload)
        artifact_id = new_id("artifact", "project_brief")
        self.repository.record_artifact(
            artifact_id,
            project_id,
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "relative_path": stored.relative_path,
                "purpose": "formal project brief",
            },
            recorded_at=at,
        )
        generation_id = new_id("generation", "project_brief")
        receipt_id = new_id("receipt", "project_bootstrap")
        event_id = new_id("authority_event", "project_brief_published")
        semantic_sha = hashlib.sha256(canonicalize(brief)).hexdigest()
        event_payload = {
            "event_id": event_id,
            "event_type": "formal_generation_published",
            "project_id": project_id,
            "record_type": "project_brief",
            "logical_slot": "project.brief.current",
            "generation_id": generation_id,
            "content_sha256": semantic_sha,
            "committed_at": timestamp,
        }
        event_sha = hashlib.sha256(canonicalize(event_payload)).hexdigest()
        new_root = hashlib.sha256(
            bytes.fromhex(ZERO_SHA256) + bytes.fromhex(event_sha)
        ).hexdigest()
        receipt_payload = {
            "receipt_id": receipt_id,
            "project_id": project_id,
            "source": "project_bootstrap",
            "prior_authority_sequence": 0,
            "new_authority_sequence": 1,
            "prior_authority_root_sha256": ZERO_SHA256,
            "new_authority_root_sha256": new_root,
            "prior_current_revision": 0,
            "new_current_revision": 1,
            "generations": [generation_id],
            "current_slots": {"project.brief.current": generation_id},
            "committed_at": timestamp,
        }
        receipt_sha = hashlib.sha256(canonicalize(receipt_payload)).hexdigest()
        with self.repository.publication_transaction(
            project_id,
            receipt_id,
            0,
            ZERO_SHA256,
            expected_current_revision=0,
        ) as publication:
            publication.add_formal_generation(
                generation_id,
                "project_brief",
                artifact_id,
                semantic_sha,
                brief,
                logical_slot="project.brief.current",
                published_at=at,
            )
            publication.replace_current_slot(
                "project.brief.current",
                generation_id,
                expected_generation_id=None,
                updated_at=at,
            )
            publication.append_authority_event(
                event_id,
                "formal_generation_published",
                event_sha,
                new_root,
                event_payload,
                committed_at=at,
            )
            publication.record_receipt(
                receipt_sha,
                receipt_payload,
                committed_at=at,
            )
        return payload


    def update(
        self,
        project_id: str,
        command: UpdateProjectBriefRequest,
        *,
        command_id: str,
        command_sha256: str,
        requested_by: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Replace the formal project brief without launching research work."""

        current = self.repository.get_current_record(
            project_id, "project.brief.current"
        )
        if current is None:
            raise ValueError("The project has no current formal brief.")
        prior = json.loads(str(current["payload_json"]))
        if type(prior) is not dict:
            raise ValueError("The current project brief is not a JSON object.")

        fields = command.model_fields_set
        replacement = dict(prior)
        if "research_question" in fields:
            replacement["research_question"] = str(command.research_question).strip()
        if "domains" in fields:
            replacement["domains"] = _text_items(command.domains or ())
        if "intended_use" in fields:
            replacement["intended_use"] = str(command.intended_use).strip()
        if "scope" in fields:
            replacement["scope"] = _optional_text(command.scope)
        if "decision_criteria" in fields:
            replacement["decision_criteria"] = _text_items(
                command.decision_criteria or ()
            )
        if "constraints" in fields:
            replacement["constraints"] = _text_items(command.constraints or ())

        scientific_fields = (
            "research_question",
            "domains",
            "intended_use",
            "scope",
            "decision_criteria",
            "constraints",
        )
        if all(replacement.get(key) == prior.get(key) for key in scientific_fields):
            raise ValueError("The submitted project brief does not change formal content.")

        at = now or utc_now()
        timestamp = isoformat_utc(at)
        receipt_id = new_id("receipt", "project_brief_update")
        generation_id = new_id("generation", "project_brief")
        replacement.update(
            {
                "schema_version": "1.0.0",
                "record_id": str(prior.get("record_id", new_id("record", "project_brief"))),
                "record_type": "project_brief",
                "project_id": project_id,
                "generation_id": generation_id,
                "supersedes_generation_id": str(current["generation_id"]),
                "updated_at": timestamp,
                "published_at": timestamp,
                "publication_receipt_id": receipt_id,
                "change_summary": command.reason.strip(),
            }
        )
        replacement.pop("content_sha256", None)
        semantic_sha = hashlib.sha256(canonicalize(replacement)).hexdigest()
        replacement["content_sha256"] = semantic_sha
        bytes_payload = (
            json.dumps(replacement, ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        ).encode("utf-8")
        stored = self.artifacts.put_bytes(bytes_payload)
        artifact_id = new_id("artifact", "project_brief")
        self.repository.record_artifact(
            artifact_id,
            project_id,
            str(stored.sha256),
            stored.size,
            "application/json",
            f"artifact://sha256/{stored.sha256}",
            {
                "relative_path": stored.relative_path,
                "purpose": "formal project brief",
                "source_command_id": command_id,
            },
            recorded_at=at,
        )

        project = self.repository.get_project(project_id)
        prior_sequence = int(project["authority_sequence"])
        prior_root = str(project["authority_root_sha256"])
        prior_revision = int(project["current_revision"])
        event_documents = [
            {
                "event_id": new_id("authority_event", "project_brief_published"),
                "event_type": "formal_generation_published",
                "project_id": project_id,
                "record_type": "project_brief",
                "logical_slot": "project.brief.current",
                "generation_id": generation_id,
                "content_sha256": semantic_sha,
                "source_command_id": command_id,
                "requested_by": requested_by,
                "reason": command.reason.strip(),
                "committed_at": timestamp,
            },
            {
                "event_id": new_id("authority_event", "project_brief_superseded"),
                "event_type": "formal_generation_superseded",
                "project_id": project_id,
                "record_type": "project_brief",
                "logical_slot": "project.brief.current",
                "generation_id": str(current["generation_id"]),
                "replacement_generation_id": generation_id,
                "source_command_id": command_id,
                "committed_at": timestamp,
            },
        ]
        authority_root = prior_root
        event_entries: list[tuple[dict[str, Any], str, str]] = []
        for event in event_documents:
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
                "kind": "project_brief_update_command",
                "command_id": command_id,
                "command_sha256": command_sha256,
            },
            "record_changes": [
                {
                    "record_type": "project_brief",
                    "prior_generation_id": str(current["generation_id"]),
                    "new_generation_id": generation_id,
                }
            ],
            "authority_event_ids": [
                str(event["event_id"]) for event in event_documents
            ],
            "prior_authority_sequence": prior_sequence,
            "new_authority_sequence": prior_sequence + len(event_documents),
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
                generation_id,
                "project_brief",
                artifact_id,
                semantic_sha,
                replacement,
                logical_slot="project.brief.current",
                supersedes_generation_id=str(current["generation_id"]),
                published_at=at,
            )
            publication.replace_current_slot(
                "project.brief.current",
                generation_id,
                expected_generation_id=str(current["generation_id"]),
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
        return replacement


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip()
    return result or None


def _text_items(values: Any) -> list[str]:
    result = [str(value).strip() for value in values]
    if any(not value for value in result):
        raise ValueError("Project brief lists cannot contain blank entries.")
    if len(set(result)) != len(result):
        raise ValueError("Project brief lists cannot contain duplicate entries.")
    return result


__all__ = ["ProjectCommandService"]
