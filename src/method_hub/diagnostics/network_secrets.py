"""Provider-only network and secret handling (H0.7).

Implements:
* Provider egress topology — exact DNS endpoints for common LLM providers.
* Credential delivery — secrets passed via env file, never in bwrap cmdline.
* Secret canary scan — scan captured output for leaked secrets after a run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..capabilities.network import NetworkPolicy


# --------------------------------------------------------------------------- #
# Provider egress topology                                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    """One LLM provider's network endpoint."""

    name: str
    host: str
    port: int = 443
    path_prefix: str = "/"


#: Known provider egress endpoints.  These are the ONLY external hosts a
#: diagnostic invocation is allowed to contact when network access is needed.
PROVIDER_EGRESS: dict[str, ProviderEndpoint] = {
    "openai": ProviderEndpoint("openai", "api.openai.com", 443, "/v1"),
    "anthropic": ProviderEndpoint("anthropic", "api.anthropic.com", 443, "/v1"),
    "deepseek": ProviderEndpoint("deepseek", "api.deepseek.com", 443, "/v1"),
    "openrouter": ProviderEndpoint(
        "openrouter", "openrouter.ai", 443, "/api/v1"
    ),
    "gemini": ProviderEndpoint("gemini", "generativelanguage.googleapis.com", 443, "/"),
    "custom": ProviderEndpoint("custom", "localhost", 443, "/"),
}


def provider_network_policy(provider_names: tuple[str, ...]) -> NetworkPolicy:
    """Build a network policy that allows only the declared providers.

    H0.7: the default is deny-all.  Only when the diagnostic invocation
    needs provider API access do we allow specific provider endpoints.
    """
    if not provider_names:
        return NetworkPolicy.deny_all()
    hosts: list[str] = []
    for name in provider_names:
        endpoint = PROVIDER_EGRESS.get(name)
        if endpoint is not None:
            hosts.append(endpoint.host)
    if not hosts:
        return NetworkPolicy.deny_all()
    return NetworkPolicy.allowlist(
        hosts=tuple(hosts),
        ports=(443,),
    )


# --------------------------------------------------------------------------- #
# Credential delivery                                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CredentialDelivery:
    """How secrets are delivered to the sandbox.

    H0.7: Secrets are written to a file in the workspace directory, not
    passed via bwrap --setenv (which is visible in /proc/<pid>/cmdline).
    The file is mounted read-only inside the container at a fixed path.
    The Hermes configuration reads credentials from this file.

    The env file is deleted after the process starts.
    """

    env_file_path: Path
    secrets: Mapping[str, str] = field(default_factory=dict)

    def write(self) -> None:
        """Write the secrets as a dotenv file."""
        lines: list[str] = []
        for key, value in self.secrets.items():
            # Escape any embedded quotes.
            escaped = value.replace("'", "'\\''")
            lines.append(f"{key}='{escaped}'")
        self.env_file_path.write_text("\n".join(lines), encoding="utf-8")

    def cleanup(self) -> None:
        """Remove the env file after use."""
        try:
            self.env_file_path.unlink()
        except FileNotFoundError:
            pass

    @property
    def container_mount_point(self) -> str:
        """Where the env file is mounted inside the container."""
        return "/workspace/.secrets.env"


# --------------------------------------------------------------------------- #
# Secret canary scan                                                           #
# --------------------------------------------------------------------------- #

#: Patterns that indicate a leaked secret in captured output.
_SECRET_LEAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),
    re.compile(r"(Bearer\s+[a-zA-Z0-9._\-]{20,})"),
    re.compile(
        r"((?:api[_-]?key|token|secret|password)\s*[=:]\\s*['\"]?"
        r"[a-zA-Z0-9+/=]{16,}['\"]?)",
        re.IGNORECASE,
    ),
    # Common API key prefixes.
    re.compile(r"(AIza[a-zA-Z0-9_\\-]{35})"),  # Google
    re.compile(r"(sk-ant-[a-zA-Z0-9_\-]{20,})"),  # Anthropic
    re.compile(r"(sk-or-[a-zA-Z0-9_\-]{20,})"),  # OpenRouter
)


@dataclass(frozen=True, slots=True)
class CanaryScanResult:
    """Result of scanning captured output for leaked secrets."""

    leaks_found: int
    leaked_patterns: tuple[str, ...] = ()
    scan_target: str = ""

    @property
    def has_leaks(self) -> bool:
        return self.leaks_found > 0


def canary_scan(
    output: str,
    *,
    known_secrets: Mapping[str, str] | None = None,
    scan_target: str = "output",
) -> CanaryScanResult:
    """Scan output for leaked secrets (H0.7 canary).

    Checks for:
    1. Known secret values (exact match).
    2. Common API key patterns (regex).

    Returns a result with leak count and patterns found.
    """
    leaks: list[str] = []

    # Check known secrets first.
    if known_secrets:
        for key, value in known_secrets.items():
            if value and len(value) >= 8 and value in output:
                leaks.append(f"known_secret:{key}")

    # Check patterns.
    for pattern in _SECRET_LEAK_PATTERNS:
        matches = pattern.findall(output)
        leaks.extend(matches)

    return CanaryScanResult(
        leaks_found=len(leaks),
        leaked_patterns=tuple(leaks),
        scan_target=scan_target,
    )


def canary_scan_file(
    path: Path,
    *,
    known_secrets: Mapping[str, str] | None = None,
) -> CanaryScanResult:
    """Scan a file for leaked secrets."""
    if not path.exists():
        return CanaryScanResult(leaks_found=0, scan_target=str(path))
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return CanaryScanResult(leaks_found=0, scan_target=str(path))
    return canary_scan(
        content, known_secrets=known_secrets, scan_target=str(path)
    )


__all__ = [
    "PROVIDER_EGRESS",
    "ProviderEndpoint",
    "provider_network_policy",
    "CredentialDelivery",
    "CanaryScanResult",
    "canary_scan",
    "canary_scan_file",
]
