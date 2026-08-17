"""Immutable application-to-harness context for one prepared run."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..contracts import ResolvedPhasePlan
from ..domain import Sha256Digest, StableId
from .outputs import OutputPlan
from .preparation import PreparedRunRecipe


def _stable_id(value: StableId | str, field: str) -> StableId:
    if type(value) is StableId:
        return value
    if type(value) is str:
        return StableId(value)
    raise TypeError(f"{field} must be a StableId or string.")


def _sha256(value: Sha256Digest | str) -> Sha256Digest:
    if type(value) is Sha256Digest:
        return value
    if type(value) is str:
        return Sha256Digest(value)
    raise TypeError("manifest_sha256 must be a Sha256Digest or string.")


@dataclass(frozen=True, slots=True)
class RunExecutionContext:
    """The complete frozen basis needed by the mechanical run harness.

    Scientific role instructions and resources are supplied by the application
    while all run, phase, profile, and output choices remain bound to the
    prepared recipe.
    """

    run_id: StableId
    project_id: StableId
    manifest_sha256: Sha256Digest
    recipe: PreparedRunRecipe
    plan: ResolvedPhasePlan
    output_plan: OutputPlan
    phase_instruction: str
    role_souls: Mapping[str, str]
    preloaded_skills: Mapping[str, tuple[str, ...]]
    mode_instruction: str = ""
    researcher_instruction: str = ""
    role_instructions: Mapping[str, str] = None  # type: ignore[assignment]
    # Key format: "{stage_id}.{role}" → stage-role assignment text.
    # The task brief layers this mapping with the mode and researcher
    # instruction fields; it never selects one scientific layer with `or`.
    researcher_method_spec: str = ""
    submission_from_status: str = "running"
    submission_to_status: str = "submitted"
    identity_suffix: str = ""
    correction_command_id: str = ""
    correction_type: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _stable_id(self.run_id, "run_id"))
        object.__setattr__(
            self, "project_id", _stable_id(self.project_id, "project_id")
        )
        object.__setattr__(self, "manifest_sha256", _sha256(self.manifest_sha256))
        if type(self.recipe) is not PreparedRunRecipe:
            raise TypeError("recipe must be a PreparedRunRecipe.")
        if type(self.plan) is not ResolvedPhasePlan:
            raise TypeError("plan must be a ResolvedPhasePlan.")
        if type(self.output_plan) is not OutputPlan:
            raise TypeError("output_plan must be an OutputPlan.")
        if type(self.phase_instruction) is not str or not self.phase_instruction.strip():
            raise ValueError("phase_instruction must be nonempty text.")
        if type(self.mode_instruction) is not str:
            raise TypeError("mode_instruction must be text.")
        if not self.mode_instruction.strip():
            object.__setattr__(self, "mode_instruction", self.phase_instruction)
        if type(self.researcher_instruction) is not str:
            raise TypeError("researcher_instruction must be text.")
        if type(self.identity_suffix) is not str:
            raise TypeError("identity_suffix must be text.")
        if type(self.correction_command_id) is not str:
            raise TypeError("correction_command_id must be text.")
        if type(self.correction_type) is not str:
            raise TypeError("correction_type must be text.")
        if str(self.manifest_sha256) != self.recipe.sha256:
            raise ValueError("manifest_sha256 must equal the prepared recipe digest.")

        recipe = self.recipe.document
        expected = {
            "run_id": str(self.run_id),
            "project_id": str(self.project_id),
            "phase": self.plan.identity.phase_id,
            "mode": self.plan.mode_id,
        }
        for field, value in expected.items():
            if recipe.get(field) != value:
                raise ValueError(
                    f"Prepared recipe {field!r} does not match the execution context."
                )

        instruction_values = tuple(
            value
            for key, value in self.plan.choice_values.items()
            if key.endswith(".instructions")
        )
        if instruction_values != (self.phase_instruction,):
            raise ValueError(
                "phase_instruction must exactly match the resolved phase instruction."
            )

        roles = tuple(
            step.role for stage in self.plan.stages for step in stage.role_steps
        )
        role_set = set(roles)
        recipe_profiles = {
            str(role["role"]): str(role["profile"])
            for stage in recipe.get("stages", ())
            for role in stage.get("roles", ())
        }
        if set(recipe_profiles) != role_set:
            raise ValueError("Prepared recipe profiles do not cover the selected roles.")

        souls = dict(self.role_souls)
        missing_souls = sorted(
            role
            for role in role_set
            if type(souls.get(role)) is not str or not souls[role].strip()
        )
        if missing_souls:
            raise ValueError(f"Role souls are missing for {missing_souls}.")
        object.__setattr__(self, "role_souls", MappingProxyType(souls))

        raw_skills = dict(self.preloaded_skills)
        if any(type(values) not in {tuple, list} for values in raw_skills.values()):
            raise ValueError("Each preloaded skill set must be a tuple or list.")
        skills = {role: tuple(values) for role, values in raw_skills.items()}
        unknown_skills = sorted(set(skills) - role_set)
        if unknown_skills:
            raise ValueError(f"Skills are configured for unknown roles {unknown_skills}.")
        if any(
            type(skill) is not str or not skill.strip()
            for values in skills.values()
            for skill in values
        ):
            raise ValueError("Preloaded skill names must be nonempty text.")
        object.__setattr__(self, "preloaded_skills", MappingProxyType(skills))
        if (
            type(self.submission_from_status) is not str
            or not self.submission_from_status.strip()
            or type(self.submission_to_status) is not str
            or not self.submission_to_status.strip()
        ):
            raise ValueError("Submission statuses must be nonempty text.")

    @property
    def timeout_seconds(self) -> int:
        constraints = self.recipe.document.get("user_request", {}).get(
            "resource_constraints", {}
        )
        value = constraints.get("wall_time_limit_seconds", 14_400)
        if type(value) is not int or value < 1:
            raise ValueError("The prepared wall-time limit must be a positive integer.")
        return value

    def profile_for(self, role: str) -> str:
        for stage in self.recipe.document["stages"]:
            for item in stage["roles"]:
                if item["role"] == role:
                    return str(item["profile"])
        raise KeyError(role)


__all__ = ["RunExecutionContext"]
