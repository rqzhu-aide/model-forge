"""Network policy: deny-by-default with optional host allowlist.

The policy is declarative — it describes what *should* be reachable.  The
executor (currently the one-shot bwrap wrapper) enforces it at runtime by
configuring the sandbox network namespace.  In deny-all mode the sandbox gets
a private network namespace with no interfaces.  In allowlist mode the
sandbox gets a loopback + a proxied connection to each declared host.

Under ADR-012 network enforcement is workflow discipline, not a security
guarantee; it is sealed into the manifest and recorded in the invocation
document so the exact declared posture is auditable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class NetworkPolicyError(ValueError):
    """A network policy declaration is invalid."""


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    """Declarative network access policy for one role invocation."""

    mode: str  # "deny_all" or "allowlist"
    allowed_hosts: tuple[str, ...] = ()
    allowed_ports: tuple[int, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in ("deny_all", "allowlist"):
            raise NetworkPolicyError(
                f"Invalid network mode {self.mode!r}: must be 'deny_all' or 'allowlist'"
            )
        if self.mode == "deny_all" and self.allowed_hosts:
            raise NetworkPolicyError(
                "deny_all mode must not declare any allowed hosts"
            )
        for host in self.allowed_hosts:
            if not isinstance(host, str) or not host.strip():
                raise NetworkPolicyError(f"Invalid host {host!r}")
        for port in self.allowed_ports:
            if not isinstance(port, int) or not (1 <= port <= 65535):
                raise NetworkPolicyError(f"Invalid port {port!r}")

    @property
    def is_deny_all(self) -> bool:
        return self.mode == "deny_all"

    @property
    def has_network(self) -> bool:
        return self.mode == "allowlist" and bool(self.allowed_hosts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "allowed_hosts": list(self.allowed_hosts),
            "allowed_ports": list(self.allowed_ports),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> NetworkPolicy:
        return cls(
            mode=str(data.get("mode", "deny_all")),
            allowed_hosts=tuple(str(h) for h in data.get("allowed_hosts", ())),
            allowed_ports=tuple(int(p) for p in data.get("allowed_ports", ())),
        )

    @classmethod
    def deny_all(cls) -> NetworkPolicy:
        """No network access whatsoever."""
        return cls(mode="deny_all")

    @classmethod
    def allowlist(
        cls,
        *,
        hosts: tuple[str, ...],
        ports: tuple[int, ...] = (443,),
    ) -> NetworkPolicy:
        """Allow connections to specific hosts only."""
        return cls(mode="allowlist", allowed_hosts=hosts, allowed_ports=ports)


def default_policy_for_phase(phase_id: str) -> NetworkPolicy:
    """Return the default network policy for a phase.

    All phases default to deny_all unless explicitly configured otherwise.
    A phase author may override this via the phase contract.
    """
    return NetworkPolicy.deny_all()


__all__ = [
    "NetworkPolicy",
    "NetworkPolicyError",
    "default_policy_for_phase",
]
