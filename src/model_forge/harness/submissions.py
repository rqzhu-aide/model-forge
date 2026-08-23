"""Cancellation-fenced assembly of one immutable run submission."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..digests.jcs import canonicalize
from ..domain import Sha256Digest, StableId
from ..json_io import loads_json
from ..orchestration import (
    StageOutcome,
    StageStatus,
    SubmissionOutcome,
    SubmissionReference,
    SubmissionStatus,
)
from ..schemas import SchemaCatalog
from ..storage import ArtifactStore
from ..storage.repository import HubRepository
from .execution_context import RunExecutionContext
from .role_execution import (
    RoleClosureResult,
    RoleLifecycleError,
    RoleLifecycleService,
    deterministic_id,
    document_sha256,
)


class SubmissionAssemblyError(RuntimeError):
    """A run cannot cross the immutable submission gate safely."""


class SubmissionAssembler:
    def __init__(
        self,
        *,
        context: RunExecutionContext,
        repository: HubRepository,
        schemas: SchemaCatalog,
        artifacts: ArtifactStore,
        roles: RoleLifecycleService,
    ) -> None:
        self.context = context
        self.repository = repository
        self.schemas = schemas
        self.artifacts = artifacts
        self.roles = roles

    def submit_or_reconcile(
        self, *, stage_outcomes: tuple[StageOutcome, ...]
    ) -> SubmissionOutcome:
        prior = self.repository.get_submission(str(self.context.run_id))
        # A base submission normally short-circuits; a correction re-entry
        # (submission_from_status == "correcting") assembles a corrected
        # document and seals it as the next submission attempt instead.
        if (
            prior is not None
            and self.context.submission_from_status != "correcting"
        ):
            return self._prior_outcome(prior)
        if self.repository.cancellation_requested(str(self.context.run_id)):
            return SubmissionOutcome(SubmissionStatus.CANCELLED)
        self._require_successful_stage_chain(stage_outcomes)
        closures = self._load_closure_chain()
        document = self._assemble_document(closures)
        issues = self.schemas.validate("run-submission.schema.json", document)
        if issues:
            first = issues[0]
            raise SubmissionAssemblyError(
                f"Assembled submission is structurally invalid at "
                f"{first.json_pointer or '/'}: {first.message}"
            )

        run = self.repository.get_run(str(self.context.run_id))
        if run["status"] != self.context.submission_from_status:
            if self.repository.cancellation_requested(str(self.context.run_id)):
                return SubmissionOutcome(SubmissionStatus.CANCELLED)
            prior = self.repository.get_submission(str(self.context.run_id))
            if prior is not None:
                return self._prior_outcome(prior)
            raise SubmissionAssemblyError(
                f"Run status {run['status']!r} cannot enter the submission gate."
            )
        if prior is not None:
            return self._seal_correction_attempt(run=run, document=document)
        event_payload = {
            "event_type": "run_submitted",
            "run_id": str(self.context.run_id),
            "submission_id": document["submission_id"],
            "submission_sha256": document["submission_sha256"],
            "from_status": self.context.submission_from_status,
            "to_status": self.context.submission_to_status,
        }
        event_sha256 = document_sha256(event_payload)
        event_id = deterministic_id(
            "event",
            str(self.context.run_id),
            document["submission_id"],
            document["submission_sha256"],
        )
        run_payload = loads_json(
            run["payload_json"], source=f"run {self.context.run_id}"
        )
        if type(run_payload) is not dict:
            raise SubmissionAssemblyError("Run payload must remain a JSON object.")
        run_payload["submission_id"] = document["submission_id"]
        run_payload["submission_sha256"] = document["submission_sha256"]
        run_payload["current_stage_label"] = None
        result = self.repository.seal_submission(
            str(self.context.run_id),
            str(document["submission_id"]),
            str(document["submission_sha256"]),
            self.context.submission_from_status,
            int(run["head_sequence"]),
            self.context.submission_to_status,
            document,
            run_payload,
            event_id,
            event_sha256,
            event_payload,
        )
        if result.applied or result.reason == "already_applied":
            return SubmissionOutcome(
                SubmissionStatus.SUBMITTED,
                SubmissionReference(
                    StableId(str(document["submission_id"])),
                    Sha256Digest(str(document["submission_sha256"])),
                ),
            )
        if result.reason == "cancellation_fenced":
            return SubmissionOutcome(SubmissionStatus.CANCELLED)
        prior = self.repository.get_submission(str(self.context.run_id))
        if prior is not None:
            return self._prior_outcome(prior)
        raise SubmissionAssemblyError(
            f"Submission gate rejected the run: {result.reason}."
        )

    def _seal_correction_attempt(
        self, *, run: Any, document: dict[str, Any]
    ) -> SubmissionOutcome:
        """Seal a corrected submission over an existing base row (K-1a5).

        The base ``run_submissions`` row is immutable, so the corrected
        document is appended to ``run_submission_attempts`` and the run is
        CASed correcting -> submitted.  The attempt insert and the CAS are
        two writes; a crash between them leaves an orphaned attempt row,
        which is harmless: the table is immutable and the retry seals the
        next ordinal (latest-ordinal wins at read time).
        """
        run_id = str(self.context.run_id)
        attempt_ordinal = self.repository.count_submission_attempts(run_id) + 1
        attempt_id = f"submission-attempt.{run_id}.{attempt_ordinal}"
        self.repository.insert_submission_attempt(
            run_id,
            attempt_id,
            str(document["submission_id"]),
            attempt_ordinal,
            json.dumps(document, sort_keys=True),
            str(document["submission_sha256"]),
            correction_command_id=self.context.correction_command_id or None,
            correction_type=self.context.correction_type or None,
        )
        event_payload = {
            "event_type": "run_submitted",
            "run_id": run_id,
            "submission_id": document["submission_id"],
            "submission_sha256": document["submission_sha256"],
            "from_status": self.context.submission_from_status,
            "to_status": self.context.submission_to_status,
            "submission_attempt_id": attempt_id,
        }
        event_sha256 = document_sha256(event_payload)
        # The attempt ordinal joins the event id derivation so the correction
        # event never collides with the base submission's run_submitted event.
        event_id = deterministic_id(
            "event",
            run_id,
            str(document["submission_id"]),
            str(document["submission_sha256"]),
            str(attempt_ordinal),
        )
        run_payload = loads_json(run["payload_json"], source=f"run {run_id}")
        if type(run_payload) is not dict:
            raise SubmissionAssemblyError("Run payload must remain a JSON object.")
        run_payload["submission_id"] = document["submission_id"]
        run_payload["submission_sha256"] = document["submission_sha256"]
        run_payload["current_stage_label"] = None
        result = self.repository.compare_and_swap_run(
            run_id,
            expected_status=self.context.submission_from_status,
            expected_sequence=int(run["head_sequence"]),
            new_status=self.context.submission_to_status,
            payload=run_payload,
            event_id=event_id,
            event_sha256=event_sha256,
            event_payload=event_payload,
        )
        if result.applied:
            return SubmissionOutcome(
                SubmissionStatus.SUBMITTED,
                SubmissionReference(
                    StableId(str(document["submission_id"])),
                    Sha256Digest(str(document["submission_sha256"])),
                ),
            )
        raise SubmissionAssemblyError(
            f"Correction submission gate rejected the run: {result.reason}."
        )

    def _require_successful_stage_chain(
        self, outcomes: tuple[StageOutcome, ...]
    ) -> None:
        if len(outcomes) != len(self.context.plan.stages):
            raise SubmissionAssemblyError(
                "Submission requires one outcome for every selected contract stage."
            )
        for stage, outcome in zip(self.context.plan.stages, outcomes, strict=True):
            if (
                outcome.sequence != stage.sequence
                or str(outcome.stage_id) != stage.stage_id
                or outcome.status is not StageStatus.SUCCEEDED
            ):
                raise SubmissionAssemblyError(
                    f"Stage {stage.stage_id!r} is not successfully closed."
                )

    def _load_closure_chain(self) -> tuple[RoleClosureResult, ...]:
        closures: list[RoleClosureResult] = []
        for stage in self.context.plan.stages:
            for step in stage.role_steps:
                closure = self.roles.load_existing(stage=stage, role=step.role)
                if closure is None or closure.status.value != "succeeded":
                    raise SubmissionAssemblyError(
                        f"Role {step.role!r} in {stage.stage_id!r} lacks a successful closure."
                    )
                closures.append(closure)
        return tuple(closures)

    def _assemble_document(
        self, closures: tuple[RoleClosureResult, ...]
    ) -> dict[str, Any]:
        manifest_bytes = canonicalize(dict(self.context.recipe.document))
        manifest_stored = self.artifacts.put_bytes(
            manifest_bytes, expected_sha256=str(self.context.manifest_sha256)
        )
        manifest_artifact_id = deterministic_id(
            "artifact", "run_manifest", str(self.context.run_id)
        )
        self.repository.record_artifact(
            manifest_artifact_id,
            str(self.context.project_id),
            str(manifest_stored.sha256),
            manifest_stored.size,
            "application/json",
            f"artifact://sha256/{manifest_stored.sha256}",
            {
                "kind": "prepared_run_recipe",
                "run_id": str(self.context.run_id),
                "storage_relative_path": manifest_stored.relative_path,
            },
        )

        closure_chain: list[dict[str, Any]] = []
        submitted_artifacts: list[dict[str, Any]] = []
        closure_iterator = iter(closures)
        for stage in self.context.plan.stages:
            for step in stage.role_steps:
                try:
                    closure = next(closure_iterator)
                except StopIteration as error:
                    raise SubmissionAssemblyError(
                        "The recovered role closure chain ended early."
                    ) from error
                if closure.role != step.role:
                    raise SubmissionAssemblyError(
                        f"Role closure order does not match {stage.stage_id!r}."
                    )
                assert closure.closure_id is not None
                assert closure.closure_sha256 is not None
                assert closure.closure_artifact_id is not None
                closure_artifact = self._artifact_pointer(closure.closure_artifact_id)
                closure_chain.append(
                    {
                        "sequence": stage.sequence,
                        "stage_id": stage.stage_id,
                        "role": step.role,
                        "invocation_start_id": closure.invocation_id,
                        "start_sha256": closure.invocation_sha256,
                        "invocation_closure_id": closure.closure_id,
                        "closure_artifact": closure_artifact,
                        "closure_sha256": closure.closure_sha256,
                        "terminal_status": "succeeded",
                    }
                )
                for output in closure.outputs:
                    submitted_artifacts.append(
                        {
                            "output_id": output.output_id,
                            "contract_output_id": output.contract_output_id,
                            "source_invocation_closure_id": closure.closure_id,
                            "source_closure_sha256": closure.closure_sha256,
                            "artifact": output.artifact_pointer(
                                str(self.context.run_id)
                            ),
                        }
                    )
        try:
            next(closure_iterator)
        except StopIteration:
            pass
        else:
            raise SubmissionAssemblyError(
                "The recovered role closure chain contains extra records."
            )
        if len({item["contract_output_id"] for item in submitted_artifacts}) != len(
            submitted_artifacts
        ):
            raise SubmissionAssemblyError("Submission output identities are not unique.")
        expected_order = [spec.contract_output_id for spec in self.context.output_plan.specs]
        submitted_artifacts.sort(
            key=lambda item: expected_order.index(item["contract_output_id"])
        )
        lead_candidates = [item for item in closure_chain if item["role"] == "research_lead"]
        if not lead_candidates:
            raise SubmissionAssemblyError("Submission requires a research-lead closure.")
        lead = lead_candidates[-1]
        submitted_at = max(
            item.closed_at for item in closures if item.closed_at is not None
        )
        submission_id = deterministic_id(
            "submission", str(self.context.run_id), str(self.context.manifest_sha256)
        )
        document: dict[str, Any] = {
            "schema_version": "1.0.0",
            "submission_id": submission_id,
            "run_id": str(self.context.run_id),
            "project_id": str(self.context.project_id),
            "phase": self.context.plan.identity.phase_id,
            "mode": self.context.plan.mode_id,
            "manifest_binding": {
                "artifact": {
                    "artifact_id": manifest_artifact_id,
                    "uri": f"run://{self.context.run_id}/artifact/{manifest_artifact_id}",
                    "path": manifest_stored.relative_path,
                    "sha256": str(manifest_stored.sha256),
                    "media_type": "application/json",
                },
                "manifest_sha256": str(self.context.manifest_sha256),
            },
            "closure_chain": closure_chain,
            "lead_closure": {
                "invocation_closure_id": lead["invocation_closure_id"],
                "closure_sha256": lead["closure_sha256"],
            },
            "submitted_artifacts": submitted_artifacts,
            "submitted_at": submitted_at,
        }
        document["submission_sha256"] = document_sha256(document)
        return document

    def _artifact_pointer(self, artifact_id: str) -> dict[str, Any]:
        with self.repository.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise RoleLifecycleError(f"Artifact record {artifact_id!r} is missing.")
        metadata = loads_json(row["payload_json"], source=f"artifact {artifact_id}")
        relative_path = metadata.get("storage_relative_path")
        if type(relative_path) is not str:
            raise RoleLifecycleError(
                f"Artifact record {artifact_id!r} lacks its storage path."
            )
        self.artifacts.verify(str(row["sha256"]))
        return {
            "artifact_id": artifact_id,
            "uri": f"run://{self.context.run_id}/artifact/{artifact_id}",
            "path": relative_path,
            "sha256": str(row["sha256"]),
            "media_type": str(row["media_type"]),
        }

    def _prior_outcome(self, row: Any) -> SubmissionOutcome:
        document = loads_json(
            row["payload_json"], source=f"submission for {self.context.run_id}"
        )
        if (
            type(document) is not dict
            or document.get("run_id") != str(self.context.run_id)
            or document.get("submission_id") != row["submission_id"]
            or document.get("submission_sha256") != row["submission_sha256"]
        ):
            raise SubmissionAssemblyError("Stored submission identity is inconsistent.")
        unhashed = dict(document)
        digest = unhashed.pop("submission_sha256", None)
        if document_sha256(unhashed) != digest:
            raise SubmissionAssemblyError("Stored submission digest is invalid.")
        return SubmissionOutcome(
            SubmissionStatus.SUBMITTED,
            SubmissionReference(
                StableId(str(row["submission_id"])),
                Sha256Digest(str(row["submission_sha256"])),
            ),
        )


__all__ = ["SubmissionAssembler", "SubmissionAssemblyError"]
