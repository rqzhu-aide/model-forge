"""Invocation fencing: prevent duplicate advancement of role invocations.

This module builds on the **existing** durable execution records
(``role_execution_intents``, ``role_execution_acknowledgements``,
``role_execution_heartbeats``, ``role_execution_closures``) — it does not
create a parallel lease store.

The fencing token is a monotonically increasing counter per invocation.
A stale token cannot launch, heartbeat, cancel, or close.  The coordinator
lease is an in-memory time-boxed lock (one coordinator process per server
instance) that prevents two concurrent advance attempts on the same invocation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..storage.repository import HubRepository


@dataclass(frozen=True, slots=True)
class FencingToken:
    """Monotonically increasing token for one invocation."""

    execution_id: str
    token: int
    issued_at: str


@dataclass(slots=True)
class CoordinatorLease:
    """Time-boxed lease on one invocation."""

    execution_id: str
    lease_id: str
    token: int
    acquired_at: float
    expires_at: float
    holder: str


class FencingError(RuntimeError):
    """A fencing or lease violation."""


class InvocationFencer:
    """Enforce single-advancement and no-rerun invariants for invocations.

    The lease is in-memory (one coordinator per server instance).  The
    fencing token counter is also in-memory but is seeded from the durable
    heartbeat sequence on first access, so a restart continues from the
    correct point.
    """

    def __init__(
        self,
        repository: HubRepository,
        *,
        lease_ttl_seconds: int = 120,
    ) -> None:
        self._repository = repository
        self._lease_ttl = lease_ttl_seconds
        self._tokens: dict[str, int] = {}
        self._leases: dict[str, CoordinatorLease] = {}

    # -- fencing tokens ---------------------------------------------------

    def current_token(self, execution_id: str) -> FencingToken:
        """Return the current fencing token for an invocation.

        Seeds from the durable heartbeat sequence on first access.
        """
        if execution_id not in self._tokens:
            self._tokens[execution_id] = self._seed_from_heartbeats(execution_id)
        return FencingToken(
            execution_id=execution_id,
            token=self._tokens[execution_id],
            issued_at="",
        )

    def check_fence(self, execution_id: str, token: FencingToken) -> bool:
        """Return True if *token* is the current token for *execution_id*."""
        current = self.current_token(execution_id)
        return current.token == token.token

    def advance(self, execution_id: str, token: FencingToken) -> FencingToken:
        """Atomically increment the fencing token.

        Requires the caller to hold the current token.  Raises if the
        invocation is terminal (no-rerun invariant).
        """
        if self.is_terminal(execution_id):
            raise FencingError(
                f"Invocation {execution_id!r} is terminal — cannot advance"
            )
        current = self.current_token(execution_id)
        if token.token != current.token:
            raise FencingError(
                f"Stale fencing token for {execution_id!r}: "
                f"expected {current.token}, got {token.token}"
            )
        next_token = current.token + 1
        self._tokens[execution_id] = next_token
        return FencingToken(
            execution_id=execution_id,
            token=next_token,
            issued_at="",
        )

    # -- coordinator lease ------------------------------------------------

    def acquire_lease(self, execution_id: str, holder: str) -> CoordinatorLease:
        """Create or take over a time-boxed lease.

        Raises if another active lease exists and has not expired.
        """
        self._expire_stale(execution_id)
        existing = self._leases.get(execution_id)
        if existing is not None and existing.holder != holder:
            raise FencingError(
                f"Lease for {execution_id!r} held by {existing.holder!r}"
            )
        now = time.monotonic()
        token = self.current_token(execution_id)
        lease = CoordinatorLease(
            execution_id=execution_id,
            lease_id=str(uuid.uuid4()),
            token=token.token,
            acquired_at=now,
            expires_at=now + self._lease_ttl,
            holder=holder,
        )
        self._leases[execution_id] = lease
        return lease

    def renew_lease(
        self, execution_id: str, holder: str
    ) -> CoordinatorLease:
        """Extend the lease if still held by *holder*."""
        self._expire_stale(execution_id)
        existing = self._leases.get(execution_id)
        if existing is None or existing.holder != holder:
            raise FencingError(
                f"Cannot renew lease for {execution_id!r}: not held by {holder!r}"
            )
        existing.expires_at = time.monotonic() + self._lease_ttl
        return existing

    def release_lease(self, execution_id: str) -> None:
        """Release the lease, allowing another coordinator to acquire it."""
        self._leases.pop(execution_id, None)

    def holds_lease(self, execution_id: str, holder: str) -> bool:
        """Check whether *holder* currently holds an active lease."""
        self._expire_stale(execution_id)
        lease = self._leases.get(execution_id)
        return lease is not None and lease.holder == holder

    # -- no-rerun invariant -----------------------------------------------

    def is_terminal(self, execution_id: str) -> bool:
        """Check whether a closure exists for *execution_id*."""
        with self._repository._database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM role_execution_closures WHERE execution_id = ? LIMIT 1",
                (execution_id,),
            ).fetchone()
            return row is not None

    # -- internals --------------------------------------------------------

    def _seed_from_heartbeats(self, execution_id: str) -> int:
        """Seed the token counter from the last heartbeat sequence."""
        try:
            with self._repository._database.connect() as connection:
                row = connection.execute(
                    "SELECT MAX(sequence) AS max_seq "
                    "FROM role_execution_heartbeats WHERE execution_id = ?",
                    (execution_id,),
                ).fetchone()
                if row is not None and row["max_seq"] is not None:
                    return int(row["max_seq"])
        except Exception:
            pass
        return 0

    def _expire_stale(self, execution_id: str) -> None:
        """Remove expired leases."""
        lease = self._leases.get(execution_id)
        if lease is not None and time.monotonic() >= lease.expires_at:
            del self._leases[execution_id]


__all__ = [
    "CoordinatorLease",
    "FencingError",
    "FencingToken",
    "InvocationFencer",
]
