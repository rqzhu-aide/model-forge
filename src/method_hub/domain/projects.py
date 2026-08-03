"""Project bootstrap and researcher-facing project summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..errors import DomainValidationError
from .identities import StableId
from .runs import isoformat_utc


@dataclass(frozen=True, slots=True)
class Project:
    project_id: StableId
    name: str
    brief: str
    owner_user_id: StableId
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if type(self.project_id) is str:
            object.__setattr__(self, "project_id", StableId(self.project_id))
        if type(self.owner_user_id) is str:
            object.__setattr__(self, "owner_user_id", StableId(self.owner_user_id))
        if type(self.name) is not str or not self.name.strip():
            raise DomainValidationError(
                "project.invalid_name", "Project name must be nonempty.", field="name"
            )
        if type(self.brief) is not str or not self.brief.strip():
            raise DomainValidationError(
                "project.invalid_brief",
                "Project brief must state the research question and scope.",
                field="brief",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": str(self.project_id),
            "name": self.name,
            "brief": self.brief,
            "owner_user_id": str(self.owner_user_id),
            "created_at": isoformat_utc(self.created_at),
            "updated_at": isoformat_utc(self.updated_at),
        }


__all__ = ["Project"]
