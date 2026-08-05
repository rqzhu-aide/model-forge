"""Strict transport models shared by the HTTP API and Web client.

These models describe projections and commands. They do not compute eligibility,
scientific status, or workflow state. Those values come from the application
service behind the API port.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyString = Annotated[str, StringConstraints(min_length=1)]
Sha256String = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

PhaseId = Literal["P1", "P2", "P3", "P4", "P5"]
RunLifecycleState = Literal[
    "created",
    "preparing",
    "prepared",
    "running",
    "cancellation_requested",
    "submitted",
    "validating",
    "promoting",
    "published",
    "failed",
    "rejected",
    "conflicted",
    "cancelled",
]
StageState = Literal[
    "pending", "running", "stopping", "succeeded", "failed", "cancelled"
]
ActionType = Literal[
    "start_run",
    "cancel_run",
    "retire_method",
    "reactivate_method",
    "withdraw_formal_generation",
    "update_project_brief",
    "save_profile",
    "install_skill",
]


class StrictModel(BaseModel):
    """Base model that rejects undeclared or coerced transport fields."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True)


class MethodIdentity(StrictModel):
    stable_id: NonEmptyString
    version: int = Field(ge=1)
    definition_sha256: Sha256String


class ProjectionStamp(StrictModel):
    current_index_generation_id: NonEmptyString | None = None
    authority_event_root_sha256: Sha256String | None = None
    projected_at: NonEmptyString | None = None
    view_revision: int | None = Field(default=None, ge=0)


class CommandContract(StrictModel):
    phase: PhaseId
    phase_contract_version: NonEmptyString
    phase_contract_sha256: Sha256String
    mode: NonEmptyString


class ActionDescriptor(StrictModel):
    descriptor_id: NonEmptyString
    action_type: ActionType
    execution_kind: Literal[
        "research_run", "control_transaction", "configuration"
    ] | None = None
    enabled: bool
    reason_code: NonEmptyString | None = None
    researcher_message: NonEmptyString | None = None
    consequence_summary: NonEmptyString
    command_contract: CommandContract | None = None
    method_identity: MethodIdentity | None = None
    method_id: NonEmptyString | None = None
    run_id: NonEmptyString | None = None
    target_id: NonEmptyString | None = None
    requires_reason: bool | None = None

    @model_validator(mode="after")
    def explain_disabled_action(self) -> "ActionDescriptor":
        if not self.enabled and (
            self.reason_code is None or self.researcher_message is None
        ):
            raise ValueError(
                "a disabled action requires reason_code and researcher_message"
            )
        return self


class ProjectSummary(StrictModel):
    project_id: NonEmptyString
    name: NonEmptyString
    research_question: NonEmptyString
    domains: list[NonEmptyString]
    updated_at: NonEmptyString | None = None
    active_run_count: int = Field(ge=0)


class AttentionSummary(StrictModel):
    attention_id: NonEmptyString
    severity: Literal[
        "informational", "monitor", "reassessment_required", "blocking"
    ]
    question: NonEmptyString
    phase: PhaseId | None = None
    method_id: NonEmptyString | None = None


class ScientificStatus(StrictModel):
    publication_state: Literal[
        "run_local", "submitted", "validated", "formal", "withdrawn", "invalid"
    ] | None = None
    record_position: Literal["current", "historical", "none"] | None = None
    alignment: Literal[
        "exact", "compatible", "unassessed", "outdated", "not_applicable"
    ] | None = None
    attention: Literal[
        "none", "monitor", "reassessment_required", "blocking"
    ] | None = None
    attention_count: int | None = Field(default=None, ge=0)
    scientific_outcome: Literal[
        "supported",
        "partially_supported",
        "contradicted",
        "inconclusive",
        "not_assessed",
        "not_applicable",
    ] | None = None
    last_published_at: NonEmptyString | None = None


class MethodRow(StrictModel):
    identity: MethodIdentity
    display_name: NonEmptyString
    aliases: list[NonEmptyString] | None = None
    lifecycle_state: Literal["proposed", "active", "retired"]
    summary: str
    mathematical_summary: str
    definition_artifact: ArtifactLink | None = None
    assumptions: list[str] | None = None
    provenance_summary: str | None = None
    novelty_summary: str | None = None
    feasibility_summary: str | None = None
    principal_risks: list[str] | None = None
    phase_statuses: dict[PhaseId, ScientificStatus]
    actions: list[ActionDescriptor]


class LiteratureSummary(StrictModel):
    source_count: int = Field(ge=0)
    coverage_summary: str
    current_synthesis: str
    status: ScientificStatus


class PhaseNavigationSummary(StrictModel):
    phase_id: PhaseId
    name: NonEmptyString
    navigation_state: Literal[
        "no_current_record",
        "active_run",
        "current_records",
        "attention_required",
    ]
    formal_record_count: int = Field(ge=0)
    method_scoped_record_count: int = Field(ge=0)
    active_run_count: int = Field(ge=0)
    latest_published_at: NonEmptyString | None = None
    assessment: ScientificStatus
    summary: NonEmptyString


class ProjectStorageView(StrictModel):
    storage_kind: Literal["backend_managed"] = "backend_managed"
    open_folder_supported: Literal[False] = False
    display_path: NonEmptyString | None = None
    explanation: NonEmptyString


class ProjectOverview(StrictModel):
    project: ProjectSummary
    project_brief: ProjectBriefView
    literature_summary: LiteratureSummary | None = None
    methods: list[MethodRow]
    phases: list[PhaseNavigationSummary]
    active_runs: list[RunSummary]
    attention_items: list[AttentionSummary]
    storage: ProjectStorageView
    actions: list[ActionDescriptor]
    projection: ProjectionStamp


class EvidenceLink(StrictModel):
    label: NonEmptyString
    href: NonEmptyString | None = None


class AvailableAction(StrictModel):
    label: NonEmptyString
    consequence: NonEmptyString


class DecisionBrief(StrictModel):
    headline: str
    current_decision: str
    current_conclusion: str
    fundamental_contribution: str
    what_changed: str
    strongest_evidence: list[EvidenceLink]
    principal_uncertainty: str
    principal_risk: str
    material_disagreement: str
    rerun_question: str
    available_actions: list[AvailableAction]


class ArtifactLink(StrictModel):
    artifact_id: NonEmptyString
    label: NonEmptyString
    information_layer: Literal["primary", "structured", "compact"]
    media_type: NonEmptyString | None = None
    href: NonEmptyString


class ProjectBriefView(StrictModel):
    project_id: NonEmptyString
    record_id: NonEmptyString
    generation_id: NonEmptyString
    research_question: NonEmptyString
    domains: list[NonEmptyString]
    intended_use: NonEmptyString
    scope: str | None = None
    decision_criteria: list[NonEmptyString]
    constraints: list[NonEmptyString]
    scope_note: str
    published_at: NonEmptyString
    artifact: ArtifactLink
    actions: list[ActionDescriptor]
    projection: ProjectionStamp


class SystemSettingsView(StrictModel):
    service_version: NonEmptyString
    bind_host: NonEmptyString
    port: int = Field(ge=1, le=65_535)
    executor_kind: Literal["disabled", "fake", "hermes_kanban"]
    execution_available: bool
    development_mode: bool
    data_root: NonEmptyString
    database_path: NonEmptyString
    artifact_namespace: NonEmptyString
    architecture_root: NonEmptyString
    frontend_dist: NonEmptyString
    frontend_available: bool
    database_schema_version: int = Field(ge=0)
    project_count: int = Field(ge=0)
    settings_editable_in_ui: Literal[False] = False
    settings_message: NonEmptyString


class CurrentRecordView(StrictModel):
    record_id: NonEmptyString
    generation_id: NonEmptyString
    title: NonEmptyString
    summary: str
    source_run_id: NonEmptyString
    published_at: NonEmptyString
    method_identity: MethodIdentity | None = None
    basis_summary: str
    change_summary: str
    status: ScientificStatus


class ArtifactPointer(StrictModel):
    artifact_id: NonEmptyString
    uri: NonEmptyString
    sha256: Sha256String


class ContextOption(StrictModel):
    option_id: NonEmptyString
    label: NonEmptyString
    description: str
    artifact_pointer: ArtifactPointer | None = None
    generation_id: NonEmptyString | None = None
    selected_by_default: bool
    required: bool
    disabled: bool | None = None
    disabled_reason: str | None = None


class RunModeOption(StrictModel):
    mode_id: NonEmptyString
    label: NonEmptyString
    description: str


class StagePlanItem(StrictModel):
    stage_id: NonEmptyString
    label: NonEmptyString
    roles: list[NonEmptyString]
    execution: Literal["serial", "parallel"]


class RunConfigurationView(StrictModel):
    modes: list[RunModeOption]
    default_mode: NonEmptyString
    instruction_label: NonEmptyString
    instruction_help: str
    instruction_placeholder: str | None = None
    current_inputs: list[ContextOption]
    history_options: list[ContextOption]
    stage_plan: list[StagePlanItem]


class EvidenceSummary(StrictModel):
    evidence_id: NonEmptyString
    label: NonEmptyString
    assessment: str
    eligibility: Literal[
        "included", "excluded", "unassessed", "not_applicable"
    ] | None = None
    method_match: str | None = None
    href: NonEmptyString | None = None


class PhaseView(StrictModel):
    phase_id: PhaseId
    name: NonEmptyString
    purpose: str
    current_record: CurrentRecordView | None = None
    assessment: ScientificStatus
    decision_brief: DecisionBrief | None = None
    evidence: list[EvidenceSummary]
    artifacts: list[ArtifactLink]
    run_configuration: RunConfigurationView
    actions: list[ActionDescriptor]
    active_runs: list[RunSummary]
    recent_runs: list[RunSummary]
    descriptor_basis: dict | None = None  # internal: for sealed_basis extraction
    projection: ProjectionStamp
    empty_state_message: str | None = None


class RunStage(StrictModel):
    sequence: int = Field(ge=1)
    stage_id: NonEmptyString
    label: NonEmptyString
    roles: list[NonEmptyString]
    execution: Literal["serial", "parallel"]
    status: StageState
    started_at: NonEmptyString | None = None
    completed_at: NonEmptyString | None = None
    activity: str | None = None
    last_heartbeat_at: NonEmptyString | None = None
    stale_after_seconds: int | None = Field(default=None, ge=1)


class RunSummary(StrictModel):
    run_id: NonEmptyString
    phase: PhaseId
    mode: NonEmptyString
    state: RunLifecycleState
    method_identity: MethodIdentity | None = None
    requested_at: NonEmptyString
    updated_at: NonEmptyString
    current_stage_label: str | None = None
    actions: list[ActionDescriptor]


class RunEvent(StrictModel):
    sequence: int = Field(ge=1)
    event_id: NonEmptyString
    event_type: NonEmptyString
    state: RunLifecycleState | None = None
    stage_id: NonEmptyString | None = None
    role: NonEmptyString | None = None
    message: str
    occurred_at: NonEmptyString


class RunContract(StrictModel):
    phase_contract_version: NonEmptyString
    phase_contract_sha256: Sha256String


class FrozenBasisItem(StrictModel):
    label: NonEmptyString
    identity: NonEmptyString
    digest: Sha256String


class TerminalReason(StrictModel):
    code: NonEmptyString
    message: NonEmptyString
    smallest_correction: str | None = None


class ValidationReportView(StrictModel):
    status: Literal["pending", "passed", "failed"]
    summary: str
    href: NonEmptyString | None = None


class PublicationReceiptView(StrictModel):
    publication_id: NonEmptyString
    published_at: NonEmptyString
    href: NonEmptyString | None = None


class PublicationReceiptDocument(StrictModel):
    format: Literal["method-hub.publication-receipt"]
    format_version: Literal["1.0.0"]
    receipt_id: NonEmptyString
    project_id: NonEmptyString
    run_id: NonEmptyString
    command_id: NonEmptyString
    phase: PhaseId
    record_changes: list[dict[str, Any]]
    cumulative_object_changes: list[dict[str, Any]]
    authority_events: list[dict[str, Any]]
    prior_authority_sequence: int = Field(ge=0)
    new_authority_sequence: int = Field(ge=0)
    prior_authority_root_sha256: Sha256String
    new_authority_root_sha256: Sha256String
    prior_current_revision: int = Field(ge=0)
    new_current_revision: int = Field(ge=0)
    atomic: Literal[True]
    published_at: NonEmptyString
    content_sha256: Sha256String

    @model_validator(mode="after")
    def enforce_monotone_heads(self) -> "PublicationReceiptDocument":
        if self.new_authority_sequence < self.prior_authority_sequence:
            raise ValueError("new authority sequence cannot precede the prior sequence")
        if self.new_current_revision < self.prior_current_revision:
            raise ValueError("new current revision cannot precede the prior revision")
        return self


class RunDetail(RunSummary):
    requested_by: NonEmptyString
    instructions: str
    contract: RunContract
    frozen_basis: list[FrozenBasisItem]
    stage_plan: list[RunStage]
    last_event_sequence: int = Field(ge=0)
    last_event_at: NonEmptyString | None = None
    stale_after_seconds: int | None = Field(default=None, ge=1)
    terminal_reason: TerminalReason | None = None
    validation_report: ValidationReportView | None = None
    publication_receipt: PublicationReceiptView | None = None


class ExpectedOutput(StrictModel):
    """One declared expected output of a supervised run (WP-F1a).

    ``path`` is relative to the run's ``outputs/`` directory.  Only the
    relative-ness is checked at the transport layer; the seal/preflight
    machinery re-checks the full output contract (``..`` escapes,
    pre-existing outputs) before any process is launched.
    """

    output_id: NonEmptyString
    path: NonEmptyString
    required_fields: list[NonEmptyString] | None = None


class StartSupervisedRunRequest(StrictModel):
    """Explicit user command to seal and launch one supervised run (WP-F1a).

    Every start is an explicit command: nothing in the service starts a
    run automatically.  Provider keys are never accepted here — they come
    only from the server process environment via the allowlist, so any
    request body attempting to smuggle credentials fails schema
    validation (``extra='forbid'``).
    """

    invocation_id: NonEmptyString
    idempotency_key: NonEmptyString
    role: NonEmptyString
    phase: NonEmptyString
    method_identity: dict[str, Any] | None = None
    brief_text: str
    expected_outputs: list[ExpectedOutput] = Field(default_factory=list)
    memory_policy: Literal["persistent", "ephemeral", "read_only"]
    #: Recorded in the seal manifest's ``user_choices`` metadata; the
    #: launcher resolves the effective timeout from it.
    model: NonEmptyString | None = None
    provider: NonEmptyString | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)


class SupervisedRunSummary(StrictModel):
    """One sealed supervised invocation, condensed for list views (WP-F0).

    ``phase``, ``method_identity``, and ``memory_policy`` come from the
    stored, digest-verified manifest JSON and are null when that document
    is no longer readable (for example after WP-E3 retention pruned the
    run directory).  Everything else comes from the seal registry and the
    launch/validation/promotion tables.
    """

    invocation_id: NonEmptyString
    seal_id: NonEmptyString
    role: NonEmptyString
    phase: NonEmptyString | None = None
    method_identity: dict[str, Any] | None = None
    memory_policy: NonEmptyString | None = None
    sealed_at: NonEmptyString
    latest_launch_status: Literal[
        "running", "succeeded", "failed", "cancelled"
    ] | None = None
    validation_verdict: Literal["pass", "fail"] | None = None
    promoted: bool


class SupervisedManifestSummary(StrictModel):
    """Selected fields of the immutable seal manifest (never the full bytes)."""

    project_id: NonEmptyString
    role: NonEmptyString
    phase: NonEmptyString
    method_identity: dict[str, Any] | None = None
    memory_snapshot: dict[str, Any] | None = None
    session_snapshot: dict[str, Any] | None = None
    expected_outputs: list[dict[str, Any]]
    hermes: dict[str, Any] | None = None
    role_asset_digests: dict[str, str]
    sealed_at: NonEmptyString


class SupervisedLaunchRecord(StrictModel):
    """One durable launch record of a supervised invocation (WP-E0)."""

    launch_id: NonEmptyString
    status: Literal["running", "succeeded", "failed", "cancelled"]
    exit_code: int | None = None
    external_execution_id: NonEmptyString | None = None
    task_brief_sha256: Sha256String | None = None
    launched_at: NonEmptyString
    closed_at: NonEmptyString | None = None


class SupervisedValidationReport(StrictModel):
    """The latest stored output-validation report for one invocation (WP-E1)."""

    launch_id: NonEmptyString
    verdict: Literal["pass", "fail"]
    validated_at: NonEmptyString
    checks: list[dict[str, str]]


class SupervisedPromotionRecord(StrictModel):
    """One allowlisted memory/session promotion record (WP-E2)."""

    record_id: NonEmptyString
    promoted_at: NonEmptyString
    status: Literal["succeeded", "failed"]
    before_digest: dict[str, Any]
    after_digest: dict[str, Any]
    backup_paths: dict[str, Any]


class SupervisedPreflightReport(StrictModel):
    """The latest stored preflight report for one invocation (WP-F1c)."""

    report_id: NonEmptyString
    verdict: Literal["pass", "fail"]
    created_at: NonEmptyString
    checks: list[dict[str, str]]


class SupervisedRunDetail(StrictModel):
    """The complete durable read view of one supervised invocation (WP-F0)."""

    invocation_id: NonEmptyString
    seal_id: NonEmptyString
    project_id: NonEmptyString
    role: NonEmptyString
    sealed_at: NonEmptyString
    manifest: SupervisedManifestSummary | None = None
    manifest_note: NonEmptyString | None = None
    preflight_report: SupervisedPreflightReport | None = None
    preflight_note: NonEmptyString | None = None
    launches: list[SupervisedLaunchRecord]
    validation: SupervisedValidationReport | None = None
    promotions: list[SupervisedPromotionRecord]


class SkillStatus(StrictModel):
    skill_id: NonEmptyString
    name: NonEmptyString
    description: str
    required: bool
    status: Literal["installed", "missing", "update_available", "unavailable"]
    installed_version: str | None = None
    recommended_version: str | None = None
    source_revision: str | None = None
    status_detail: str
    actions: list[ActionDescriptor]


class ProfileOption(StrictModel):
    profile_id: NonEmptyString
    label: NonEmptyString
    version: NonEmptyString
    enabled: bool
    researcher_message: NonEmptyString | None = None
    action_descriptor_id: NonEmptyString

    @model_validator(mode="after")
    def explain_disabled_option(self) -> "ProfileOption":
        if not self.enabled and self.researcher_message is None:
            raise ValueError("a disabled profile option requires a researcher message")
        return self


class RoleProfileView(StrictModel):
    role_id: NonEmptyString
    display_name: NonEmptyString
    role_summary: str
    profile_id: NonEmptyString
    profile_version: NonEmptyString
    profile_options: list[ProfileOption]
    scientific_stance_summary: str
    model_summary: str
    memory_policy_summary: str
    applicable_phases: list[PhaseId]
    skills: list[SkillStatus]
    actions: list[ActionDescriptor]


class ProfileConfigurationView(StrictModel):
    profiles: list[RoleProfileView]
    projection: ProjectionStamp


class StartRunRequest(StrictModel):
    action_descriptor_id: NonEmptyString
    phase: PhaseId
    mode: NonEmptyString
    choice_values: dict[str, Any]
    context_policy: Literal["current_only", "current_plus_selected_history"]
    selected_context_option_ids: list[NonEmptyString]

    @model_validator(mode="after")
    def selected_current_inputs_are_unique(self) -> "StartRunRequest":
        if len(self.selected_context_option_ids) != len(
            set(self.selected_context_option_ids)
        ):
            raise ValueError("selected current input IDs must be unique")
        return self


class CreateProjectRequest(StrictModel):
    name: NonEmptyString
    research_question: NonEmptyString
    domains: list[NonEmptyString]
    intended_use: NonEmptyString
    scope: str | None = None
    decision_criteria: list[NonEmptyString] = Field(default_factory=list)
    constraints: list[NonEmptyString] = Field(default_factory=list)


class UpdateProjectBriefRequest(StrictModel):
    action_descriptor_id: NonEmptyString
    reason: NonEmptyString
    research_question: NonEmptyString | None = None
    domains: list[NonEmptyString] | None = None
    intended_use: NonEmptyString | None = None
    scope: str | None = None
    decision_criteria: list[NonEmptyString] | None = None
    constraints: list[NonEmptyString] | None = None

    @model_validator(mode="after")
    def changes_at_least_one_scientific_field(self) -> "UpdateProjectBriefRequest":
        fields = {
            "research_question",
            "domains",
            "intended_use",
            "scope",
            "decision_criteria",
            "constraints",
        }
        if not (self.model_fields_set & fields):
            raise ValueError(
                "a project brief update must supply at least one scientific field"
            )
        return self


class ReasonedActionRequest(StrictModel):
    action_descriptor_id: NonEmptyString
    reason: NonEmptyString


class SaveProfileRequest(StrictModel):
    profile_id: NonEmptyString
    action_descriptor_id: NonEmptyString


class InstallSkillRequest(StrictModel):
    action_descriptor_id: NonEmptyString


# --------------------------------------------------------------------------- #
# Block 2: Role-definition configuration service models
# --------------------------------------------------------------------------- #


class SkillRecommendationView(StrictModel):
    skill_id: NonEmptyString
    name: NonEmptyString
    description: str
    source: NonEmptyString
    recommended_version: NonEmptyString


class CustomSkillView(StrictModel):
    skill_id: NonEmptyString
    name: NonEmptyString
    description: str
    source: NonEmptyString


class BaseConfigurationView(StrictModel):
    file_name: NonEmptyString
    format: Literal["yaml", "json"]
    content_sha256: Sha256String


class LibraryGuidanceView(StrictModel):
    file_name: NonEmptyString
    content_sha256: Sha256String


class RoleDefinitionView(StrictModel):
    """Complete role definition: SOUL, configuration, skills, guidance."""

    role_id: NonEmptyString
    display_name: NonEmptyString
    profile_version: NonEmptyString
    default_profile: NonEmptyString
    applicable_phases: list[PhaseId]
    soul_text: str
    soul_sha256: Sha256String
    base_configuration: BaseConfigurationView
    recommended_skills: list[SkillRecommendationView]
    custom_skills: list[CustomSkillView]
    library_guidance: LibraryGuidanceView


class RoleDefinitionCatalogView(StrictModel):
    """All four role definitions."""

    roles: list[RoleDefinitionView]


class AssetStatusView(StrictModel):
    asset_type: Literal[
        "soul", "base_configuration", "library_guidance", "skill"
    ]
    file_name: NonEmptyString
    status: Literal["present", "missing", "customized", "unavailable"]
    expected_sha256: Sha256String
    actual_sha256: Sha256String | None = None
    source: NonEmptyString | None = None
    recommended_version: NonEmptyString | None = None
    detail: str


class RoleHealthReportView(StrictModel):
    role_id: NonEmptyString
    display_name: NonEmptyString
    profile_available: bool
    profile_name: NonEmptyString | None = None
    overall_status: Literal["healthy", "incomplete", "customized", "unavailable"]
    soul_status: AssetStatusView
    configuration_status: AssetStatusView
    guidance_status: AssetStatusView
    skill_statuses: list[AssetStatusView]
    conditions: list[
        Literal[
            "healthy",
            "hermes_missing",
            "profile_missing",
            "soul_customized",
            "soul_missing",
            "config_customized",
            "config_missing",
            "skill_mismatch",
            "skill_missing",
            "skill_unavailable",
            "bundle_missing",
        ]
    ]
    detail: str


class ConfigurationHealthView(StrictModel):
    """Aggregate health across all role definitions."""

    hermes_root: NonEmptyString
    hermes_available: bool
    roles: list[RoleHealthReportView]
    overall_status: Literal["healthy", "incomplete", "customized", "unavailable"]
    conditions: list[
        Literal[
            "healthy",
            "hermes_missing",
            "profile_missing",
            "soul_customized",
            "soul_missing",
            "config_customized",
            "config_missing",
            "skill_mismatch",
            "skill_missing",
            "skill_unavailable",
            "bundle_missing",
        ]
    ]


class ProvisionRoleRequest(StrictModel):
    action_descriptor_id: NonEmptyString | None = None
    install_skills: bool = True
    force_overwrite_assets: bool = False
    force_overwrite_skills: bool = False


class ProvisionResultView(StrictModel):
    role_id: NonEmptyString
    profile_name: NonEmptyString
    assets_written: list[NonEmptyString]
    skills_installed: list[NonEmptyString]
    rolled_back: bool


class ConflictDetailView(StrictModel):
    """Details of a customization conflict surfaced to the user."""

    role_id: NonEmptyString
    asset_type: Literal[
        "soul", "base_configuration", "library_guidance", "skill"
    ]
    file_name: NonEmptyString
    expected_sha256: Sha256String
    actual_sha256: Sha256String
    resolution_options: list[
        Literal["keep_custom", "overwrite_with_reference"]
    ]


# Rebuild models that refer to classes declared later in this module.
MethodRow.model_rebuild()
ProjectOverview.model_rebuild()
PhaseView.model_rebuild()
