"""Durable researcher-facing progress around narrow orchestration services."""

from __future__ import annotations

import json

from ..contracts import ResolvedStage
from ..domain import Sha256Digest, StableId
from ..domain.runs import isoformat_utc, utc_now
from ..orchestration import StageOutcome, SubmissionOutcome
from ..orchestration.protocol import OrchestrationServices
from .run_lifecycle import RunLifecycle


class ProgressReportingServices:
    def __init__(
        self,
        services: OrchestrationServices,
        lifecycle: RunLifecycle,
    ) -> None:
        self.services = services
        self.lifecycle = lifecycle

    async def cancellation_requested(
        self, *, run_id: StableId, manifest_sha256: Sha256Digest
    ) -> bool:
        return await self.services.cancellation_requested(
            run_id=run_id, manifest_sha256=manifest_sha256
        )

    async def execute_or_reconcile_stage(
        self,
        *,
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        stage: ResolvedStage,
    ) -> StageOutcome:
        self._stage_progress(
            str(run_id),
            stage,
            status="running",
            activity="The declared role group is running.",
            completed=False,
        )
        try:
            outcome = await self.services.execute_or_reconcile_stage(
                run_id=run_id,
                manifest_sha256=manifest_sha256,
                stage=stage,
            )
        except Exception:
            self._stage_progress(
                str(run_id),
                stage,
                status="failed",
                activity="The role group stopped before a valid closure was sealed.",
                completed=True,
            )
            raise
        self._stage_progress(
            str(run_id),
            stage,
            status=outcome.status.value,
            activity=f"The role group finished with status {outcome.status.value}.",
            completed=True,
        )
        return outcome

    async def submit_or_reconcile(
        self,
        *,
        run_id: StableId,
        manifest_sha256: Sha256Digest,
        stage_outcomes: tuple[StageOutcome, ...],
    ) -> SubmissionOutcome:
        return await self.services.submit_or_reconcile(
            run_id=run_id,
            manifest_sha256=manifest_sha256,
            stage_outcomes=stage_outcomes,
        )

    def _stage_progress(
        self,
        run_id: str,
        stage: ResolvedStage,
        *,
        status: str,
        activity: str,
        completed: bool,
    ) -> None:
        row = self.lifecycle.repository.get_run(run_id)
        if row["status"] != "running":
            return
        payload = json.loads(row["payload_json"])
        states = dict(payload.get("stage_states", {}))
        prior = dict(states.get(stage.stage_id, {}))
        now = isoformat_utc(utc_now())
        prior.update(
            {
                "status": status,
                "activity": activity,
                "last_heartbeat_at": now,
                "stale_after_seconds": 300,
            }
        )
        prior.setdefault("started_at", now)
        if completed:
            prior["completed_at"] = now
        states[stage.stage_id] = prior
        self.lifecycle.progress(
            run_id,
            activity,
            payload_updates={
                "stage_states": states,
                "current_stage_label": None if completed else stage.objective,
            },
            details={"stage_id": stage.stage_id, "stage_status": status},
        )


__all__ = ["ProgressReportingServices"]
