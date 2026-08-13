"""Load and render default phase instructions from Jinja2 template files.

Default instructions live as ``.md`` Jinja2 templates under::

    resources/instructions/<Phase>/<stage_id>.<role>.md   (stage + role)
    resources/instructions/<Phase>/<stage_id>.md           (stage, all roles)
    resources/instructions/<Phase>/<mode>.<role>.md        (mode + role)
    resources/instructions/<Phase>/<mode>.md               (mode, shared)
    resources/instructions/<Phase>/default.<role>.md       (default + role)
    resources/instructions/<Phase>/default.md              (shared default)

At runtime the loader can resolve mode and stage-role templates as separate
prompt layers. Templates receive the project brief plus ``phase_id``,
``mode_id``, ``mode_slug``, ``stage_id``, and ``role``, so a stage-role
template can give different assignments in different modes.

Users edit ``.md`` files directly — adding ``{{ variable }}`` placeholders,
changing the directive text, or creating role-specific overrides — without
touching Python code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from jinja2 import Environment, FileSystemLoader, StrictUndefined

# Resolve the instructions directory relative to the project root.
# This file lives at src/method_hub/application/default_instructions.py
_INSTRUCTIONS_DIR = (
    Path(__file__).resolve()
    .parents[3]  # project root
    / "resources"
    / "instructions"
)

_jinja_env = Environment(
    loader=FileSystemLoader(str(_INSTRUCTIONS_DIR)),
    undefined=StrictUndefined,
    autoescape=False,
)

# Harness-owned vs agent-authored field separation (HV-4.6). Appended to
# every rendered instruction layer unless the template already carries the
# exact sentence, so the guidance renders exactly once per layer and also
# covers templates that predate this note.
_HARNESS_FIELD_OWNERSHIP_GUIDANCE = (
    "You are responsible for the scientific content of your output. "
    "The harness populates identity, provenance, timestamps, and digest "
    "fields automatically. Do not attempt to write these fields."
)


def instructions_dir() -> Path:
    """Return the base directory holding instruction ``.md`` templates."""
    return _INSTRUCTIONS_DIR


def _parse_mode(mode_or_phase: str) -> tuple[str, str]:
    """Return ``(phase, slug)`` from a mode string.

    ``"p2.full_catalog"`` → ``("P2", "full_catalog")``
    ``"P2"``              → ``("P2", "default")``
    """
    if "." in mode_or_phase:
        prefix, slug = mode_or_phase.split(".", 1)
        return prefix.upper(), slug
    return mode_or_phase.upper(), "default"


def _stage_candidates(
    phase_or_mode: str,
    *,
    role: str,
    stage_id: str,
) -> list[str]:
    """Return stage-only candidates, most mode-specific first."""
    phase, slug = _parse_mode(phase_or_mode)
    candidates: list[str] = []
    if stage_id and slug != "default" and role:
        candidates.append(f"{phase}/{stage_id}.{slug}.{role}.md")
    if stage_id and slug != "default":
        candidates.append(f"{phase}/{stage_id}.{slug}.md")
    if stage_id and role:
        candidates.append(f"{phase}/{stage_id}.{role}.md")
    if stage_id:
        candidates.append(f"{phase}/{stage_id}.md")
    return candidates


def _mode_candidates(phase_or_mode: str, *, role: str) -> list[str]:
    """Return mode-only candidates, followed by phase defaults."""
    phase, slug = _parse_mode(phase_or_mode)
    candidates: list[str] = []
    if role:
        candidates.append(f"{phase}/{slug}.{role}.md")
    candidates.append(f"{phase}/{slug}.md")
    if role:
        candidates.append(f"{phase}/default.{role}.md")
    candidates.append(f"{phase}/default.md")
    return candidates


def _first_existing(candidates: list[str]) -> str:
    for candidate in candidates:
        try:
            _jinja_env.get_template(candidate)
            return candidate
        except Exception:
            continue
    raise FileNotFoundError(
        f"No instruction template found. Searched: {', '.join(candidates)}"
    )


def _resolve_template_name(phase_or_mode: str, role: str = "", stage_id: str = "") -> str:
    """Resolve the template relative path using the fallback chain.

    The chain tries, in order:
      1. ``<Phase>/<stage_id>.<mode>.<role>.md``
      2. ``<Phase>/<stage_id>.<mode>.md``
      3. ``<Phase>/<stage_id>.<role>.md``
      4. ``<Phase>/<stage_id>.md``
      5. ``<Phase>/<mode>.<role>.md``
      6. ``<Phase>/<mode>.md``
      7. ``<Phase>/default.<role>.md``
      8. ``<Phase>/default.md``
    """
    candidates = _stage_candidates(
        phase_or_mode, role=role, stage_id=stage_id
    ) + _mode_candidates(phase_or_mode, role=role)
    try:
        return _first_existing(candidates)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"No instruction template found for {phase_or_mode!r}"
            + (f", stage={stage_id!r}" if stage_id else "")
            + (f", role={role!r}" if role else "")
            + f". Searched: {', '.join(candidates)}"
        ) from error


def stage_template_exists(phase_or_mode: str, role: str = "", stage_id: str = "") -> bool:
    """Return True if a stage-assignment template exists.

    This includes both mode-specific and generic stage templates. The run
    coordinator loads the result as a separate assignment layer; it never
    replaces either the mode directive or researcher-authored direction.
    """
    candidates = _stage_candidates(
        phase_or_mode, role=role, stage_id=stage_id
    )
    for candidate in candidates:
        try:
            _jinja_env.get_template(candidate)
            return True
        except Exception:
            continue
    return False


def _render(
    template_name: str,
    phase_or_mode: str,
    brief: Mapping[str, Any],
    *,
    role: str,
    stage_id: str,
) -> str:
    phase, slug = _parse_mode(phase_or_mode)
    template = _jinja_env.get_template(template_name)
    context = {
        "research_question": brief.get("research_question", "") or "",
        "scope": brief.get("scope", "") or "Not specified.",
        "constraints": brief.get("constraints") or [],
        "decision_criteria": brief.get("decision_criteria") or [],
        "phase_id": phase,
        "mode_id": (
            f"{phase.lower()}.{slug}"
            if slug != "default"
            else phase.lower()
        ),
        "mode_slug": slug,
        "stage_id": stage_id,
        "role": role,
    }
    rendered = template.render(**context)
    while "\n\n\n" in rendered:
        rendered = rendered.replace("\n\n\n", "\n\n")
    rendered = rendered.strip()
    if _HARNESS_FIELD_OWNERSHIP_GUIDANCE not in rendered:
        rendered = f"{rendered}\n\n{_HARNESS_FIELD_OWNERSHIP_GUIDANCE}"
    return rendered


def load_mode_instruction(
    phase_or_mode: str,
    brief: Mapping[str, Any],
    *,
    role: str = "",
) -> str:
    """Render only the mode-level instruction layer."""
    template_name = _first_existing(
        _mode_candidates(phase_or_mode, role=role)
    )
    return _render(
        template_name,
        phase_or_mode,
        brief,
        role=role,
        stage_id="",
    )


def load_stage_instruction(
    phase_or_mode: str,
    brief: Mapping[str, Any],
    *,
    role: str,
    stage_id: str,
) -> str:
    """Render only the stage-role assignment layer."""
    template_name = _first_existing(
        _stage_candidates(phase_or_mode, role=role, stage_id=stage_id)
    )
    return _render(
        template_name,
        phase_or_mode,
        brief,
        role=role,
        stage_id=stage_id,
    )


def load_instruction(
    phase_or_mode: str,
    brief: Mapping[str, Any],
    *,
    role: str = "",
    stage_id: str = "",
) -> str:
    """Load and render the default instruction.

    Parameters
    ----------
    phase_or_mode:
        Either a bare phase (``"P2"``) or a full mode (``"p2.full_catalog"``).
    brief:
        Mapping with ``research_question``, ``scope``, ``constraints``,
        ``decision_criteria`` (typically the project-brief ``row_json``).
    role:
        Optional role name (``"theorist"``, ``"data_analyst"``,
        ``"research_lead"``).
    stage_id:
        Optional stage identifier (``"p2.lead_reconciliation"``). When
        provided, a stage-specific template is preferred — letting the
        same role get different instructions in different stages.

    Returns
    -------
    str
        The rendered instruction text.
    """
    template_name = _resolve_template_name(phase_or_mode, role, stage_id)
    return _render(
        template_name,
        phase_or_mode,
        brief,
        role=role,
        stage_id=stage_id,
    )


# Backward-compatible alias
def default_instruction(phase: str, brief: Mapping[str, Any]) -> str:
    """Alias for :func:`load_instruction` (backward compatibility)."""
    return load_instruction(phase, brief)


__all__ = [
    "load_instruction",
    "load_mode_instruction",
    "load_stage_instruction",
    "default_instruction",
    "instructions_dir",
    "stage_template_exists",
]
