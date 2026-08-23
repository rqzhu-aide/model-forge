"""Small compare-and-swap helpers for durable run progress."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from ..digests.jcs import canonicalize
from ..domain.runs import RunStatus, isoformat_utc, require_transition, utc_now
from ..storage.repository import HubRepository, RunTransitionResult


class RunLifecycle:
    def __init__(self, repository: HubRepository) -> None:
        self.repository = repository

    def transition(
        self,
        run_id: str,
        target: RunStatus | str,
        message: str,
        *,
        payload_updates: Mapping[str, Any] = {},
        details: Mapping[str, Any] = {},
    ) -> RunTransitionResult:
        row = self.repository.get_run(run_id)
        current = RunStatus(str(row["status"]))
        selected = target if type(target) is RunStatus else RunStatus(target)
        require_transition(current, selected)
        return self._mutate(
            row,
            selected.value,
            message,
            payload_updates=payload_updates,
            details=details,
        )

    def progress(
        self,
        run_id: str,
        message: str,
        *,
        payload_updates: Mapping[str, Any] = {},
        details: Mapping[str, Any] = {},
    ) -> RunTransitionResult:
        row = self.repository.get_run(run_id)
        return self._mutate(
            row,
            str(row["status"]),
            message,
            payload_updates=payload_updates,
            details=details,
        )

    def _mutate(
        self,
        row: sqlite3.Row,
        target: str,
        message: str,
        *,
        payload_updates: Mapping[str, Any],
        details: Mapping[str, Any],
    ) -> RunTransitionResult:
        payload = json.loads(row["payload_json"])
        if type(payload) is not dict:
            raise ValueError("Run payload must remain a JSON object.")
        payload.update(dict(payload_updates))
        now = utc_now()
        event = {
            "event_type": f"run.{target}",
            "message": message,
            "occurred_at": isoformat_utc(now),
            "details": dict(details),
        }
        next_sequence = int(row["head_sequence"]) + 1
        event_id = "event." + hashlib.sha256(
            canonicalize(
                {
                    "run_id": str(row["run_id"]),
                    "sequence": next_sequence,
                    "status": target,
                    "payload": event,
                }
            )
        ).hexdigest()
        event_sha256 = hashlib.sha256(canonicalize(event)).hexdigest()
        return self.repository.compare_and_swap_run(
            str(row["run_id"]),
            str(row["status"]),
            int(row["head_sequence"]),
            target,
            payload,
            event_id,
            event_sha256,
            event,
            recorded_at=now,
        )


__all__ = ["RunLifecycle"]
