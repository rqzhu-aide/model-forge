"""Load and render default phase instructions from Jinja2 template files.

Default instructions live as ``.md`` Jinja2 templates under::

    resources/instructions/<Phase>/<stage_id>.<role>.md   (stage + role)
    resources/instructions/<Phase>/<stage_id>.md           (stage, all roles)
    resources/instructions/<Phase>/<mode>.<role>.md        (mode + role)
    resources/instructions/<Phase>/<mode>.md               (mode, shared)
    resources/instructions/<Phase>/default.<role>.md       (default + role)
    resources/instructions/<Phase>/default.md              (shared default)

At runtime the loader:

1. Resolves the template: stage+role files win over mode files.
2. Renders it with Jinja2, injecting the project brief's
   ``research_question``, ``scope``, ``constraints``, and
   ``decision_criteria``.

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


def _resolve_template_name(phase_or_mode: str, role: str = "", stage_id: str = "") -> str:
    """Resolve the template relative path using the fallback chain.

    The chain tries, in order:
      1. ``<Phase>/<stage_id>.<role>.md``      (stage + role specific)
      2. ``<Phase>/<stage_id>.md``              (stage specific, all roles)
      3. ``<Phase>/<mode>.<role>.md``           (mode + role specific)
      4. ``<Phase>/<mode>.md``                  (mode specific, shared)
      5. ``<Phase>/default.<role>.md``          (default + role specific)
      6. ``<Phase>/default.md``                 (shared default)
    """
    phase, slug = _parse_mode(phase_or_mode)
    candidates = []
    if stage_id and role:
        candidates.append(f"{phase}/{stage_id}.{role}.md")
    if stage_id:
        candidates.append(f"{phase}/{stage_id}.md")
    if role:
        candidates.append(f"{phase}/{slug}.{role}.md")
    candidates.append(f"{phase}/{slug}.md")
    if role:
        candidates.append(f"{phase}/default.{role}.md")
    candidates.append(f"{phase}/default.md")

    for candidate in candidates:
        try:
            _jinja_env.get_template(candidate)
            return candidate
        except Exception:
            continue

    raise FileNotFoundError(
        f"No instruction template found for {phase_or_mode!r}"
        + (f", stage={stage_id!r}" if stage_id else "")
        + (f", role={role!r}" if role else "")
        + f". Searched: {', '.join(candidates)}"
    )


def stage_template_exists(phase_or_mode: str, role: str = "", stage_id: str = "") -> bool:
    """Return True if a **stage-specific** template exists (chain levels 1-2 only).

    This checks for files at ``<Phase>/<stage_id>.<role>.md`` or
    ``<Phase>/<stage_id>.md`` — NOT the mode-level fallback (levels 3-6).

    Used by the run coordinator to decide whether to override the user's
    phase-level instruction with a stage-specific one.  When the user has
    authored custom instruction text, the coordinator must NOT shadow it
    with a mode-level template.
    """
    phase, slug = _parse_mode(phase_or_mode)
    candidates: list[str] = []
    if stage_id and role:
        candidates.append(f"{phase}/{stage_id}.{role}.md")
    if stage_id:
        candidates.append(f"{phase}/{stage_id}.md")
    for candidate in candidates:
        try:
            _jinja_env.get_template(candidate)
            return True
        except Exception:
            continue
    return False


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
    template = _jinja_env.get_template(template_name)

    context = {
        "research_question": brief.get("research_question", "") or "",
        "scope": brief.get("scope", "") or "Not specified.",
        "constraints": brief.get("constraints") or [],
        "decision_criteria": brief.get("decision_criteria") or [],
        "role": role,
    }

    rendered = template.render(**context)
    while "\n\n\n" in rendered:
        rendered = rendered.replace("\n\n\n", "\n\n")
    return rendered.strip()


# Backward-compatible alias
def default_instruction(phase: str, brief: Mapping[str, Any]) -> str:
    """Alias for :func:`load_instruction` (backward compatibility)."""
    return load_instruction(phase, brief)


__all__ = ["load_instruction", "default_instruction", "instructions_dir", "stage_template_exists"]
