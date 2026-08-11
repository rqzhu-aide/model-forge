"""Read-only application queries over the phase-neutral Hub repository."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..domain.identities import ArtifactPointer, MethodIdentity


def _extract_summary(payload: dict[str, Any]) -> str | None:
    """Extract a human-readable summary from a formal record payload.

    Different record types store text in different fields. Try the most
    informative ones first, then fall back to structural fields.
    """
    # Direct text fields — most informative
    for key in ("summary", "current_conclusion", "synthesis", "abstract", "headline"):
        value = payload.get(key)
        if type(value) is str and value.strip():
            return value.strip()
    # Scientific outcome may be a dict with a "conclusion" or "label"
    outcome = payload.get("scientific_outcome")
    if type(outcome) is dict:
        for key in ("conclusion", "label", "assessment", "summary"):
            value = outcome.get(key)
            if type(value) is str and value.strip():
                return value.strip()
    if type(outcome) is str and outcome.strip():
        return outcome.strip()
    # Method records: rationale gives the "why"
    rationale = payload.get("rationale")
    if type(rationale) is str and rationale.strip():
        return rationale.strip()
    # Project brief: research question is the most useful one-liner
    rq = payload.get("research_question")
    if type(rq) is str and rq.strip():
        return rq.strip()
    # Count-based records (library, catalog): summarize structurally
    source_count = payload.get("source_count")
    if source_count is not None:
        return f"{source_count} indexed source(s)."
    method_count = payload.get("method_count")
    active = payload.get("active_method_count")
    if method_count is not None:
        active_str = f" ({active} active)" if active is not None else ""
        return f"{method_count} method(s) in catalog{active_str}."
    return None


def _extract_highlight_artifact_id(payload: dict[str, Any]) -> str | None:
    """Extract the layer-3 (compact decision view) artifact_id from representations."""
    representations = payload.get("representations")
    if type(representations) is not list:
        return None
    for rep in representations:
        if type(rep) is not dict:
            continue
        if str(rep.get("information_layer", "")) == "compact_decision_view":
            artifact = rep.get("artifact")
            if type(artifact) is dict:
                artifact_id = artifact.get("artifact_id")
                if type(artifact_id) is str and artifact_id:
                    return artifact_id
    return None
from ..harness.inputs import CurrentRecordReference
from ..storage.repository import HubRepository, RepositoryNotFoundError


def row_json(row: sqlite3.Row, field: str = "payload_json") -> dict[str, Any]:
    value = json.loads(row[field])
    if type(value) is not dict:
        raise ValueError(f"Repository field {field!r} must contain a JSON object.")
    return value


class RepositoryQueries:
    def __init__(self, repository: HubRepository) -> None:
        self.repository = repository

    def list_projects(self) -> tuple[sqlite3.Row, ...]:
        with self.repository.database.connect() as connection:
            return tuple(
                connection.execute(
                    "SELECT * FROM projects ORDER BY updated_at DESC, project_id"
                ).fetchall()
            )

    def list_runs(
        self, project_id: str, *, phase: str | None = None
    ) -> tuple[sqlite3.Row, ...]:
        self.repository.get_project(project_id)
        with self.repository.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        if phase is None:
            return tuple(rows)
        return tuple(row for row in rows if row_json(row).get("phase") == phase)

    def list_formal_generations(
        self,
        project_id: str,
        *,
        record_type: str | None = None,
    ) -> tuple[sqlite3.Row, ...]:
        self.repository.get_project(project_id)
        parameters: tuple[str, ...]
        condition = ""
        if record_type is None:
            parameters = (project_id,)
        else:
            condition = " AND g.record_type = ?"
            parameters = (project_id, record_type)
        with self.repository.database.connect() as connection:
            return tuple(
                connection.execute(
                    """
                    SELECT g.*, a.sha256 AS artifact_sha256,
                           a.storage_uri AS artifact_storage_uri,
                           a.size AS artifact_size
                    FROM formal_generations AS g
                    JOIN artifacts AS a ON a.artifact_id = g.artifact_id
                    WHERE g.project_id = ?""" + condition + """
                    ORDER BY g.published_at DESC, g.generation_id
                    """,
                    parameters,
                ).fetchall()
            )

    def publication_receipt_for_command(
        self, project_id: str, command_id: str
    ) -> sqlite3.Row | None:
        self.repository.get_project(project_id)
        with self.repository.database.connect() as connection:
            return connection.execute(
                """
                SELECT * FROM publication_receipts
                WHERE project_id = ? AND command_id = ?
                ORDER BY committed_at DESC LIMIT 1
                """,
                (project_id, command_id),
            ).fetchone()

    def run_manifest(self, run_id: str) -> sqlite3.Row | None:
        with self.repository.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM run_manifests WHERE run_id = ?", (run_id,)
            ).fetchone()

    def run_for_command(self, command_id: str) -> sqlite3.Row | None:
        with self.repository.database.connect() as connection:
            return connection.execute(
                "SELECT * FROM runs WHERE command_id = ?", (command_id,)
            ).fetchone()

    def artifact(self, artifact_id: str) -> sqlite3.Row:
        with self.repository.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise RepositoryNotFoundError("artifact", artifact_id)
        return row

    def latest_execution_activity(self, run_id: str) -> tuple[sqlite3.Row, ...]:
        with self.repository.database.connect() as connection:
            return tuple(
                connection.execute(
                    """
                    SELECT i.*, a.external_execution_id, a.acknowledged_at,
                           c.closure_id, c.payload_json AS closure_payload_json,
                           c.closed_at,
                           h.payload_json AS heartbeat_payload_json,
                           h.recorded_at AS heartbeat_at
                    FROM role_execution_intents AS i
                    LEFT JOIN role_execution_acknowledgements AS a
                      ON a.execution_id = i.execution_id
                    LEFT JOIN role_execution_closures AS c
                      ON c.execution_id = i.execution_id
                    LEFT JOIN role_execution_heartbeats AS h
                      ON h.heartbeat_id = (
                        SELECT h2.heartbeat_id
                        FROM role_execution_heartbeats AS h2
                        WHERE h2.execution_id = i.execution_id
                        ORDER BY h2.sequence DESC LIMIT 1
                      )
                    WHERE i.run_id = ? ORDER BY i.created_at
                    """,
                    (run_id,),
                ).fetchall()
            )

    def project_authority_head(self, project_id: str) -> tuple[int, str, int]:
        row = self.repository.get_project(project_id)
        return (
            int(row["authority_sequence"]),
            str(row["authority_root_sha256"]),
            int(row["current_revision"]),
        )

    def current_record(
        self,
        *,
        project_id: str,
        record_type: str,
        method_identity: MethodIdentity | None,
        match_policy: str,
    ) -> CurrentRecordReference | None:
        """Resolve a current formal record by type and optional exact method."""
        # A method-scoped match policy with no selected method must match
        # nothing: returning the newest record of the type regardless of
        # method would silently bind method-specific context into a run
        # that never asked for a method (e.g. P2 full_catalog mode).
        if method_identity is None and match_policy in {
            "exact",
            "same_stable_method",
        }:
            return None
        candidates = [
            row
            for row in self.repository.list_current_records(project_id)
            if row["record_type"] == record_type
        ]
        matches: list[tuple[sqlite3.Row, dict[str, Any], MethodIdentity | None]] = []
        for row in candidates:
            payload = row_json(row)
            raw_method = (
                payload.get("identity")
                if record_type == "method_record"
                else payload.get("method_identity")
            )
            candidate_method = (
                MethodIdentity.from_dict(raw_method)
                if type(raw_method) is dict
                else None
            )
            if method_identity is not None:
                if candidate_method is None:
                    continue
                if match_policy == "exact" and candidate_method != method_identity:
                    continue
                if (
                    match_policy == "same_stable_method"
                    and candidate_method.stable_id != method_identity.stable_id
                ):
                    continue
            matches.append((row, payload, candidate_method))
        if not matches:
            return None
        matches.sort(
            key=lambda item: (int(item[0]["slot_revision"]), item[0]["published_at"]),
            reverse=True,
        )
        row, payload, candidate_method = matches[0]
        artifact_id = str(row["artifact_id"])
        digest = str(row["artifact_sha256"])
        summary = _extract_summary(payload)
        highlight_artifact_id = _extract_highlight_artifact_id(payload)
        size_bytes = int(row["artifact_size"]) if row["artifact_size"] is not None else None
        return CurrentRecordReference(
            record_id=str(payload.get("record_id", row["generation_id"])),
            generation_id=str(row["generation_id"]),
            generation_number=int(row["slot_revision"]),
            record_type=str(row["record_type"]),
            artifact=ArtifactPointer(
                artifact_id=artifact_id,
                uri=f"artifact://sha256/{digest}",
                sha256=digest,
                media_type="application/json",
            ),
            method_identity=candidate_method,
            logical_slot=str(row["slot_key"]),
            summary=summary,
            highlight_artifact_id=highlight_artifact_id,
            size_bytes=size_bytes,
        )


__all__ = ["RepositoryQueries", "row_json"]
