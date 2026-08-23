"""Collision-resistant stable identifiers for service-created objects."""

from __future__ import annotations

import re
import uuid


_TOKEN = re.compile(r"[^a-z0-9]+")


def slug(value: str, *, fallback: str = "item", maximum: int = 48) -> str:
    normalized = _TOKEN.sub("_", value.strip().lower()).strip("_")
    if not normalized:
        normalized = fallback
    if not normalized[0].isalpha():
        normalized = f"{fallback}_{normalized}"
    return normalized[:maximum].rstrip("_")


def new_id(kind: str, hint: str | None = None) -> str:
    prefix = slug(kind, fallback="object")
    random = uuid.uuid4().hex
    if hint:
        return f"{prefix}.{slug(hint)}.{random}"
    return f"{prefix}.{random}"


__all__ = ["new_id", "slug"]
