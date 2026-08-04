"""Tests for H0.7: provider-only network and secret handling."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from method_hub.diagnostics.network_secrets import (
    PROVIDER_EGRESS,
    CanaryScanResult,
    CredentialDelivery,
    ProviderEndpoint,
    canary_scan,
    canary_scan_file,
    provider_network_policy,
)


# --------------------------------------------------------------------------- #
# Provider network policy                                                      #
# --------------------------------------------------------------------------- #


class TestProviderNetworkPolicy:
    def test_no_providers_means_deny_all(self) -> None:
        """H0.7: no providers declared → deny-all network."""
        policy = provider_network_policy(())
        assert policy.is_deny_all
        assert not policy.has_network

    def test_single_provider_allowlist(self) -> None:
        """H0.7: one provider → only that host is allowed."""
        policy = provider_network_policy(("openai",))
        assert policy.has_network
        assert "api.openai.com" in policy.allowed_hosts
        assert 443 in policy.allowed_ports

    def test_multiple_providers(self) -> None:
        """H0.7: multiple providers → all their hosts allowed."""
        policy = provider_network_policy(("openai", "anthropic"))
        assert policy.has_network
        assert "api.openai.com" in policy.allowed_hosts
        assert "api.anthropic.com" in policy.allowed_hosts

    def test_unknown_provider_silently_ignored(self) -> None:
        policy = provider_network_policy(("openai", "unknown_provider"))
        assert policy.has_network
        assert "api.openai.com" in policy.allowed_hosts

    def test_all_known_providers_resolvable(self) -> None:
        """Every provider in PROVIDER_EGRESS has a valid endpoint."""
        for name, endpoint in PROVIDER_EGRESS.items():
            assert isinstance(endpoint, ProviderEndpoint)
            assert endpoint.host
            assert 1 <= endpoint.port <= 65535


# --------------------------------------------------------------------------- #
# Credential delivery                                                          #
# --------------------------------------------------------------------------- #


class TestCredentialDelivery:
    def test_secrets_written_to_file(self, tmp_path: Path) -> None:
        """H0.7: secrets are written to a file, not passed via cmdline."""
        env_file = tmp_path / ".secrets.env"
        delivery = CredentialDelivery(
            env_file_path=env_file,
            secrets={"API_KEY": "sk-test123", "ANOTHER": "secret"},
        )
        delivery.write()
        content = env_file.read_text()
        assert "API_KEY='sk-test123'" in content
        assert "ANOTHER='secret'" in content

    def test_cleanup_removes_file(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".secrets.env"
        delivery = CredentialDelivery(
            env_file_path=env_file,
            secrets={"KEY": "val"},
        )
        delivery.write()
        assert env_file.exists()
        delivery.cleanup()
        assert not env_file.exists()

    def test_cleanup_nonexistent_is_safe(self, tmp_path: Path) -> None:
        """cleanup() on a non-existent file doesn't raise."""
        env_file = tmp_path / ".nonexistent.env"
        delivery = CredentialDelivery(env_file_path=env_file)
        delivery.cleanup()  # Should not raise.

    def test_container_mount_point(self, tmp_path: Path) -> None:
        delivery = CredentialDelivery(env_file_path=tmp_path / ".env")
        assert delivery.container_mount_point == "/workspace/.secrets.env"

    def test_quote_escaping(self, tmp_path: Path) -> None:
        """Secrets with quotes are properly escaped."""
        env_file = tmp_path / ".secrets.env"
        delivery = CredentialDelivery(
            env_file_path=env_file,
            secrets={"KEY": "it's a secret"},
        )
        delivery.write()
        content = env_file.read_text()
        assert "it'\\''s a secret" in content


# --------------------------------------------------------------------------- #
# Canary scan                                                                  #
# --------------------------------------------------------------------------- #


class TestCanaryScan:
    def test_clean_output_no_leaks(self) -> None:
        result = canary_scan("This is normal output with no secrets.")
        assert not result.has_leaks
        assert result.leaks_found == 0

    def test_openai_key_detected(self) -> None:
        output = "Using key sk-proj1234567890abcdefXYZ"
        result = canary_scan(output)
        assert result.has_leaks
        assert result.leaks_found >= 1

    def test_bearer_token_detected(self) -> None:
        output = "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
        result = canary_scan(output)
        assert result.has_leaks

    def test_anthropic_key_detected(self) -> None:
        output = "ANTHROPIC_API_KEY=sk-ant-api03-1234567890abcdef"
        result = canary_scan(output)
        assert result.has_leaks

    def test_known_secret_exact_match(self) -> None:
        """H0.7: exact matches of known secret values are detected."""
        known = {"API_KEY": "super-secret-value-12345"}
        result = canary_scan(
            "The config uses super-secret-value-12345 for auth",
            known_secrets=known,
        )
        assert result.has_leaks
        assert any("API_KEY" in p for p in result.leaked_patterns)

    def test_short_secret_ignored(self) -> None:
        """Secrets shorter than 8 chars are not matched (avoid false positives)."""
        known = {"K": "short"}
        result = canary_scan("this is a short value", known_secrets=known)
        # "short" is 5 chars, below the 8-char threshold.
        assert not result.has_leaks or result.leaks_found == 0 or all(
            "known_secret" not in p for p in result.leaked_patterns
        )


class TestCanaryScanFile:
    def test_scan_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "output.txt"
        f.write_text("Normal content, no secrets here.")
        result = canary_scan_file(f)
        assert not result.has_leaks

    def test_scan_file_with_leak(self, tmp_path: Path) -> None:
        f = tmp_path / "logs.txt"
        f.write_text("Error: API key sk-abc123def456ghi789jkl012mno345pqr678")
        result = canary_scan_file(f)
        assert result.has_leaks

    def test_scan_nonexistent_file(self, tmp_path: Path) -> None:
        result = canary_scan_file(tmp_path / "nonexistent.txt")
        assert not result.has_leaks
