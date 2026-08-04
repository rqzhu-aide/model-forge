"""Validated deployment settings for the local Method Hub service."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="METHOD_HUB_",
        env_file=".env",
        extra="ignore",
    )

    data_root: Path = Field(default_factory=lambda: Path.home() / ".method-hub")
    architecture_root: Path | None = None
    host: str = "127.0.0.1"
    port: int = 8765
    user_id: str = "researcher.local"
    executor_kind: Literal["disabled", "fake", "hermes_kanban", "oci"] = "disabled"
    development_mode: bool = False
    #: Diagnostic lane feature flag (H0.2).  Defaults off.  When True,
    #: the diagnostic composition root is available but scientific execution
    #: is unaffected and cannot select the one-shot executor.
    diagnostic_enabled: bool = False
    hermes_executable: str = "hermes"
    hermes_board: str = "method-hub"
    hermes_root: Path | None = None
    research_lead_profile: str = "research_lead"
    theorist_profile: str = "theorist"
    data_analyst_profile: str = "data_analyst"
    outside_reviewer_profile: str = "paper_reviewer"
    frontend_dist: Path | None = None

    @field_validator("data_root")
    @classmethod
    def absolute_data_root(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("port")
    @classmethod
    def valid_port(cls, value: int) -> int:
        if not 1 <= value <= 65_535:
            raise ValueError("port must be between 1 and 65535")
        return value

    @model_validator(mode="after")
    def safe_executor_and_host(self) -> "ApplicationSettings":
        if self.executor_kind == "fake" and not self.development_mode:
            raise ValueError("The fake executor is available only in development mode.")
        if self.executor_kind == "hermes_kanban" and not self.development_mode:
            raise ValueError(
                "Direct Hermes Kanban execution is development-only until the "
                "rootless OCI capability boundary is complete."
            )
        if self.host not in {"127.0.0.1", "::1", "localhost"} and not self.development_mode:
            raise ValueError(
                "Non-loopback binding requires an explicit production authentication deployment."
            )
        return self

    def resolved_architecture_root(self) -> Path:
        if self.architecture_root is not None:
            return self.architecture_root.expanduser().resolve()
        candidate = Path(__file__).resolve().parents[3] / "architecture"
        return candidate.resolve()

    def resolved_frontend_dist(self) -> Path:
        if self.frontend_dist is not None:
            return self.frontend_dist.expanduser().resolve()
        return (Path(__file__).resolve().parents[3] / "web" / "dist").resolve()

    def profile_for(self, role: str) -> str:
        values = {
            "research_lead": self.research_lead_profile,
            "theorist": self.theorist_profile,
            "data_analyst": self.data_analyst_profile,
            "outside_reviewer": self.outside_reviewer_profile,
        }
        try:
            return values[role]
        except KeyError as error:
            raise ValueError(f"Unknown research role {role!r}.") from error


__all__ = ["ApplicationSettings"]
