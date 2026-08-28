export type PhaseId = "P1" | "P2" | "P3" | "P4" | "P5";

export type RunLifecycleState =
  | "created"
  | "preparing"
  | "prepared"
  | "running"
  | "cancellation_requested"
  | "submitted"
  | "validating"
  | "promoting"
  | "published"
  | "failed"
  | "rejected"
  | "conflicted"
  | "cancelled"
  | "correction_authorized"
  | "correcting"
  | "correction_exhausted";

export type StageState =
  | "pending"
  | "running"
  | "stopping"
  | "succeeded"
  | "failed"
  | "cancelled";

export type ActionType =
  | "start_run"
  | "cancel_run"
  | "retire_method"
  | "reactivate_method"
  | "withdraw_formal_generation"
  | "save_profile"
  | "install_skill"
  | "update_project_brief"
  | "revalidate_run"
  | "normalize_run_outputs"
  | "package_run_outputs"
  | "revise_scientific_content"
  | "request_output_correction";

export interface MethodIdentity {
  stable_id: string;
  version: number;
  definition_sha256: string;
}

export interface ProjectionStamp {
  current_index_generation_id?: string;
  authority_event_root_sha256?: string;
  projected_at?: string;
  view_revision?: number;
}

export interface ActionDescriptor {
  descriptor_id: string;
  action_type: ActionType;
  execution_kind?: "research_run" | "control_transaction" | "configuration";
  enabled: boolean;
  reason_code?: string;
  researcher_message?: string;
  consequence_summary: string;
  command_contract?: {
    phase: PhaseId;
    phase_contract_version: string;
    phase_contract_sha256: string;
    mode: string;
  };
  method_identity?: MethodIdentity;
  method_id?: string;
  run_id?: string;
  target_id?: string;
  requires_reason?: boolean;
}

// ---------------------------------------------------------------------------
// Output correction (K-1)
// ---------------------------------------------------------------------------

export type CorrectionType = "revalidate" | "normalize" | "packaging" | "scientific";

export interface CorrectionFinding {
  code: string;
  message: string;
  severity: string;
  object_id?: string | null;
  json_pointer: string;
  finding_class: string;
  blocks_publication: boolean;
  correction_class: string;
}

export interface CorrectionTransformationEntry {
  code: string;
  json_pointer: string;
  detail: string;
}

export interface OutputTransformationRecordView {
  contract_output_id: string;
  source_sha256: string;
  result_sha256: string;
  entries: CorrectionTransformationEntry[];
  primary_artifact_unchanged: boolean;
}

export interface CorrectionPreview {
  current_findings: CorrectionFinding[];
  remaining_findings: CorrectionFinding[];
  fixed_findings: CorrectionFinding[];
  transformations: OutputTransformationRecordView[];
  passing: boolean;
  output_scope: string[];
}

export interface CorrectionCommandInput {
  correction_type: CorrectionType;
  permitted_output_scope: string[];
  user_instruction?: string;
  transformation_codes?: string[];
}

export interface ProjectSummary {
  project_id: string;
  name: string;
  research_question: string;
  domains: string[];
  updated_at?: string;
  active_run_count: number;
}

export interface AttentionSummary {
  attention_id: string;
  severity: "informational" | "monitor" | "reassessment_required" | "blocking";
  question: string;
  phase?: PhaseId;
  method_id?: string;
}

export interface LiteratureGapSummary {
  attention_id: string;
  reference: string;
  raised_by_phase: PhaseId;
  method_id?: string;
}

export interface PhaseNavigationSummary {
  phase_id: PhaseId;
  name: string;
  navigation_state:
    | "no_current_record"
    | "active_run"
    | "current_records"
    | "attention_required";
  formal_record_count: number;
  method_scoped_record_count: number;
  active_run_count: number;
  latest_published_at?: string;
  assessment: ScientificStatus;
  summary: string;
}

export interface ProjectStorageView {
  storage_kind: "backend_managed";
  open_folder_supported: false;
  display_path?: string;
  explanation: string;
}

export interface ScientificStatus {
  publication_state?: "run_local" | "submitted" | "validated" | "formal" | "withdrawn" | "invalid";
  record_position?: "current" | "historical" | "none";
  alignment?: "exact" | "compatible" | "unassessed" | "outdated" | "not_applicable";
  attention?: "none" | "monitor" | "reassessment_required" | "blocking";
  attention_count?: number;
  scientific_outcome?:
    | "supported"
    | "partially_supported"
    | "contradicted"
    | "inconclusive"
    | "not_assessed"
    | "not_applicable";
  last_published_at?: string;
}

export interface MethodAxisScore {
  score: number;
  justification: string;
  issue_refs: string[];
}

export interface MethodEvaluation {
  theoretical_validity: MethodAxisScore;
  literature_positioning: MethodAxisScore;
  empirical_feasibility: MethodAxisScore;
  adjudicated_at: string;
  review_basis_ids: string[];
}

export interface MethodRow {
  identity: MethodIdentity;
  display_name: string;
  aliases?: string[];
  lifecycle_state: "proposed" | "active" | "retired";
  summary: string;
  mathematical_summary: string;
  assumptions?: string[];
  provenance_summary?: string;
  novelty_summary?: string;
  evaluation?: MethodEvaluation | null;
  feasibility_summary?: string;
  principal_risks?: string[];
  definition_artifact?: ArtifactLink;
  phase_statuses: Partial<Record<PhaseId, ScientificStatus>>;
  actions: ActionDescriptor[];
}

export interface ProjectOverview {
  project: ProjectSummary;
  project_brief: ProjectBriefView;
  literature_summary?: {
    source_count: number;
    coverage_summary: string;
    current_synthesis: string;
    status: ScientificStatus;
  };
  methods: MethodRow[];
  phases: PhaseNavigationSummary[];
  active_runs: RunSummary[];
  attention_items: AttentionSummary[];
  storage: ProjectStorageView;
  actions: ActionDescriptor[];
  projection: ProjectionStamp;
}

export interface DecisionBrief {
  headline: string;
  current_decision: string;
  current_conclusion: string;
  fundamental_contribution: string;
  what_changed: string;
  strongest_evidence: Array<{ label: string; href?: string }>;
  principal_uncertainty: string;
  principal_risk: string;
  material_disagreement: string;
  rerun_question: string;
  available_actions: Array<{ label: string; consequence: string }>;
}

export interface ArtifactLink {
  artifact_id: string;
  label: string;
  information_layer: "primary" | "structured" | "compact";
  media_type?: string;
  href: string;
}

export interface ProjectBriefView {
  project_id: string;
  record_id: string;
  generation_id: string;
  research_question: string;
  domains: string[];
  intended_use: string;
  scope?: string;
  decision_criteria: string[];
  constraints: string[];
  scope_note: string;
  published_at: string;
  artifact: ArtifactLink;
  actions: ActionDescriptor[];
  projection: ProjectionStamp;
}

export interface SystemSettingsView {
  service_version: string;
  bind_host: string;
  port: number;
  executor_kind: "disabled" | "fake" | "hermes_kanban";
  execution_available: boolean;
  development_mode: boolean;
  data_root: string;
  database_path: string;
  artifact_namespace: string;
  architecture_root: string;
  frontend_dist: string;
  frontend_available: boolean;
  database_schema_version: number;
  project_count: number;
  settings_editable_in_ui: false;
  settings_message: string;
}

export interface CurrentRecordView {
  record_id: string;
  generation_id: string;
  title: string;
  summary: string;
  source_run_id: string;
  published_at: string;
  method_identity?: MethodIdentity;
  basis_summary: string;
  change_summary: string;
  status: ScientificStatus;
}

export interface ContextOption {
  option_id: string;
  label: string;
  description: string;
  feedback?: string;
  highlight_artifact_id?: string;
  size_bytes?: number;
  group?: string;
  hidden?: boolean;
  artifact_pointer?: {
    artifact_id: string;
    uri: string;
    sha256: string;
  };
  selected_by_default: boolean;
  required: boolean;
  disabled?: boolean;
  disabled_reason?: string;
}

export interface RunModeOption {
  mode_id: string;
  label: string;
  description: string;
}

export interface StagePlanItem {
  stage_id: string;
  label: string;
  roles: string[];
  execution: "serial" | "parallel";
}

export interface RunConfigurationView {
  modes: RunModeOption[];
  default_mode: string;
  instruction_label: string;
  instruction_help: string;
  instruction_placeholder?: string;
  current_inputs: ContextOption[];
  history_options: ContextOption[];
  stage_plan: StagePlanItem[];
}

export interface EvidenceSummary {
  evidence_id: string;
  label: string;
  assessment: string;
  eligibility?: "included" | "excluded" | "unassessed" | "not_applicable";
  method_match?: string;
  href?: string;
}

export interface PhaseView {
  phase_id: PhaseId;
  name: string;
  purpose: string;
  current_record?: CurrentRecordView;
  assessment: ScientificStatus;
  decision_brief?: DecisionBrief;
  evidence: EvidenceSummary[];
  artifacts: ArtifactLink[];
  run_configuration: RunConfigurationView;
  actions: ActionDescriptor[];
  active_runs: RunSummary[];
  recent_runs: RunSummary[];
  descriptor_basis?: ReviewedBasis | null;
  projection: ProjectionStamp;
  literature_gaps?: LiteratureGapSummary[];
  empty_state_message?: string;
}

// ---------------------------------------------------------------------------
// Reviewed-basis seal (WP-F4): what a start-run action seals at review time
// ---------------------------------------------------------------------------

export interface ReviewedCurrentInput {
  option_id: string;
  generation_id: string;
  sha256: string;
}

export interface ReviewedAuthorityHead {
  authority_sequence: number;
  authority_root_sha256: string;
  current_revision: number;
}

export interface ReviewedSkill {
  skill_id: string;
  source: string;
  source_revision: string;
  bundle_sha256: string;
}

export interface ReviewedRoleResource {
  profile: string;
  profile_version: string;
  soul_sha256: string;
  skills: ReviewedSkill[];
  model: string | null;
  provider: string | null;
  memory_policy: "persistent" | "read_only" | "ephemeral";
  phase_instruction: string | null;
  tools: string | null;
}

export interface ReviewedBasis {
  authority_head: ReviewedAuthorityHead;
  reviewed_current_inputs: ReviewedCurrentInput[];
  method_identity: MethodIdentity | null;
  role_resources: Record<string, ReviewedRoleResource>;
}

export interface RunStage {
  sequence: number;
  stage_id: string;
  label: string;
  roles: string[];
  execution: "serial" | "parallel";
  status: StageState;
  started_at?: string;
  completed_at?: string;
  activity?: string;
  last_heartbeat_at?: string;
  stale_after_seconds?: number;
}

export type FindingClass =
  | "operational_failure"
  | "integrity_blocker"
  | "correctable_contract_error"
  | "scientific_claim_blocker"
  | "scientific_attention"
  | "information";

export interface FindingItem {
  code: string;
  message: string;
  object_id: string | null;
  json_pointer: string | null;
  blocks_publication: boolean;
}

export interface FindingGroup {
  finding_class: FindingClass;
  count: number;
  sample_codes: string[];
  items: FindingItem[];
}

// ---------------------------------------------------------------------------
// Lifecycle projection (HV-3): separates execution success from output
// conformance from publication from scientific outcome. Computed server-side
// from the run's status, closure findings, validation report, and publication
// receipt — no new state-machine states are introduced.
// ---------------------------------------------------------------------------

export interface RunLifecycleProjection {
  execution_state: "not_started" | "running" | "completed" | "failed" | "cancelled";
  conformance_state: "not_checked" | "passed" | "correction_required" | "integrity_rejected";
  publication_state: "not_attempted" | "published" | "withheld" | "conflicted";
  recovery_summary:
    | "ok"
    | "needs_output_correction"
    | "correction_exhausted"
    | "failed"
    | "rejected"
    | "conflicted"
    | "cancelled"
    | "in_progress";
  blocking_finding_count: number;
  correctable_finding_count: number;
  scientific_outcome: string | null;
  finding_groups: FindingGroup[];
  available_recovery_controls: string[];
}

export interface RunSummary {
  run_id: string;
  phase: PhaseId;
  mode: string;
  state: RunLifecycleState;
  method_identity?: MethodIdentity;
  requested_at: string;
  updated_at: string;
  current_stage_label?: string;
  actions: ActionDescriptor[];
  lifecycle_projection?: RunLifecycleProjection;
}

export interface RunEvent {
  sequence: number;
  event_id: string;
  event_type: string;
  state?: RunLifecycleState;
  stage_id?: string;
  role?: string;
  message: string;
  occurred_at: string;
}

export interface RunDetail extends RunSummary {
  requested_by: string;
  instructions: string;
  contract: {
    phase_contract_version: string;
    phase_contract_sha256: string;
  };
  frozen_basis: Array<{ label: string; identity: string; digest: string }>;
  stage_plan: RunStage[];
  last_event_sequence: number;
  last_event_at?: string;
  stale_after_seconds?: number;
  terminal_reason?: {
    code: string;
    message: string;
    smallest_correction?: string;
  };
  validation_report?: {
    status: "pending" | "passed" | "failed";
    summary: string;
    href?: string;
  };
  publication_receipt?: {
    publication_id: string;
    published_at: string;
    href?: string;
  };
  lifecycle_projection?: RunLifecycleProjection;
}

export interface SkillStatus {
  skill_id: string;
  name: string;
  description: string;
  required: boolean;
  status: "installed" | "missing" | "update_available" | "unavailable";
  installed_version?: string;
  recommended_version?: string;
  source_revision?: string;
  status_detail: string;
  actions: ActionDescriptor[];
}

export interface ProfileOption {
  profile_id: string;
  label: string;
  version: string;
  enabled: boolean;
  researcher_message?: string;
  action_descriptor_id: string;
}

export interface RoleProfileView {
  role_id: string;
  display_name: string;
  role_summary: string;
  profile_id: string;
  profile_version: string;
  profile_options: ProfileOption[];
  scientific_stance_summary: string;
  model_summary: string;
  memory_policy_summary: string;
  applicable_phases: PhaseId[];
  skills: SkillStatus[];
  actions: ActionDescriptor[];
}

export interface ProfileConfigurationView {
  profiles: RoleProfileView[];
  projection: ProjectionStamp;
}

// ---------------------------------------------------------------------------
// Role-definition configuration service (WP-F2)
// ---------------------------------------------------------------------------

export type ConfigurationAssetType =
  | "soul"
  | "base_configuration"
  | "library_guidance"
  | "skill";

export type ConfigurationAssetStatus = "present" | "missing" | "customized" | "unavailable";

export type ConfigurationOverallStatus = "healthy" | "incomplete" | "customized" | "unavailable";

export type ConfigurationCondition =
  | "healthy"
  | "hermes_missing"
  | "profile_missing"
  | "soul_customized"
  | "soul_missing"
  | "config_customized"
  | "config_missing"
  | "skill_mismatch"
  | "skill_missing"
  | "skill_unavailable"
  | "bundle_missing";

export interface SkillRecommendationView {
  skill_id: string;
  name: string;
  description: string;
  source: string;
  recommended_version: string;
}

export interface CustomSkillView {
  skill_id: string;
  name: string;
  description: string;
  source: string;
}

export interface BaseConfigurationView {
  file_name: string;
  format: "yaml" | "json";
  content_sha256: string;
}

export interface LibraryGuidanceView {
  file_name: string;
  content_sha256: string;
}

export interface RoleDefinitionView {
  role_id: string;
  display_name: string;
  profile_version: string;
  default_profile: string;
  applicable_phases: PhaseId[];
  soul_text: string;
  soul_sha256: string;
  base_configuration: BaseConfigurationView;
  recommended_skills: SkillRecommendationView[];
  custom_skills: CustomSkillView[];
  library_guidance: LibraryGuidanceView;
}

export interface RoleDefinitionCatalogView {
  roles: RoleDefinitionView[];
}

export interface AssetStatusView {
  asset_type: ConfigurationAssetType;
  file_name: string;
  status: ConfigurationAssetStatus;
  expected_sha256: string;
  actual_sha256?: string;
  source?: string;
  recommended_version?: string;
  detail: string;
}

export interface RoleHealthReportView {
  role_id: string;
  display_name: string;
  profile_available: boolean;
  profile_name?: string;
  overall_status: ConfigurationOverallStatus;
  soul_status: AssetStatusView;
  configuration_status: AssetStatusView;
  guidance_status: AssetStatusView;
  skill_statuses: AssetStatusView[];
  conditions: ConfigurationCondition[];
  detail: string;
}

export interface ConfigurationHealthView {
  hermes_root: string;
  hermes_available: boolean;
  roles: RoleHealthReportView[];
  overall_status: ConfigurationOverallStatus;
  conditions: ConfigurationCondition[];
}

export interface ProvisionRoleRequest {
  install_skills: boolean;
  force_overwrite_assets: boolean;
  force_overwrite_skills: boolean;
}

export interface SkillCatalogEntry {
  skill_id: string;
  content_sha256: string;
  roles: string[];
  bundled: boolean;
  name?: string;
  description?: string;
}

export interface PhaseSkillAssignment {
  phase: string;
  source: "assigned" | "default";
  skills: string[];
}

export interface RoleSkillAssignmentsView {
  role_id: string;
  phases: PhaseSkillAssignment[];
  available_skills: SkillCatalogEntry[];
  matrix_sha256?: string;
}

export interface UpdateSkillAssignmentsRequest {
  /** A list replaces the assignment (empty = no skills); null restores default. */
  skills: string[] | null;
}

export interface ProvisionResultView {
  role_id: string;
  profile_name: string;
  assets_written: string[];
  skills_installed: string[];
  rolled_back: boolean;
}

// ---------------------------------------------------------------------------
// Supervised-run service (WP-F0 read surface + WP-F1a start command)
// ---------------------------------------------------------------------------

export type SupervisedLaunchStatus = "running" | "succeeded" | "failed" | "cancelled";

export type SupervisedMemoryPolicy = "persistent" | "ephemeral" | "read_only";

export interface SupervisedRunSummary {
  invocation_id: string;
  seal_id: string;
  role: string;
  phase: string | null;
  method_identity: Record<string, unknown> | null;
  memory_policy: string | null;
  sealed_at: string;
  latest_launch_status: SupervisedLaunchStatus | null;
  validation_verdict: "pass" | "fail" | null;
  promoted: boolean;
}

export interface ExpectedOutputInput {
  output_id: string;
  path: string;
  required_fields?: string[];
}

export interface StartSupervisedRunRequest {
  invocation_id: string;
  idempotency_key: string;
  role: string;
  phase: string;
  method_identity?: { stable_id: string; version: number } | null;
  brief_text: string;
  expected_outputs: ExpectedOutputInput[];
  memory_policy: SupervisedMemoryPolicy;
  model?: string;
  provider?: string;
  timeout_seconds?: number;
}

export interface SupervisedManifestSummary {
  project_id: string;
  role: string;
  phase: string;
  method_identity: Record<string, unknown> | null;
  memory_snapshot: Record<string, unknown> | null;
  session_snapshot: Record<string, unknown> | null;
  expected_outputs: Record<string, unknown>[];
  hermes: Record<string, unknown> | null;
  role_asset_digests: Record<string, string>;
  sealed_at: string;
}

export interface SupervisedLaunchRecord {
  launch_id: string;
  status: SupervisedLaunchStatus;
  exit_code: number | null;
  external_execution_id: string | null;
  task_brief_sha256: string | null;
  launched_at: string;
  closed_at: string | null;
}

export interface SupervisedValidationReport {
  launch_id: string;
  verdict: "pass" | "fail";
  validated_at: string;
  checks: Record<string, string>[];
}

export interface SupervisedPromotionRecord {
  record_id: string;
  promoted_at: string;
  status: "succeeded" | "failed";
  before_digest: Record<string, unknown>;
  after_digest: Record<string, unknown>;
  backup_paths: Record<string, unknown>;
}

export interface SupervisedPreflightReport {
  report_id: string;
  verdict: "pass" | "fail";
  created_at: string;
  checks: Record<string, string>[];
}

export interface SupervisedRunDetail {
  invocation_id: string;
  seal_id: string;
  project_id: string;
  role: string;
  sealed_at: string;
  manifest: SupervisedManifestSummary | null;
  manifest_note: string | null;
  preflight_report: SupervisedPreflightReport | null;
  preflight_note: string | null;
  launches: SupervisedLaunchRecord[];
  validation: SupervisedValidationReport | null;
  promotions: SupervisedPromotionRecord[];
}

export interface SupervisedRunLogFile {
  relative_path: string;
  size_bytes: number;
  sha256: string | null;
}

export interface SupervisedRunLogs {
  invocation_id: string;
  heartbeat_tail: string;
  stdout_tail: string;
  stderr_tail: string;
  outputs: SupervisedRunLogFile[];
  run_dir_available: boolean;
}

export interface StartRunRequest {
  action_descriptor_id: string;
  phase: PhaseId;
  mode: string;
  choice_values: Record<string, unknown>;
  context_policy: "current_only" | "current_plus_selected_history";
  selected_context_option_ids: string[];
}

export interface CreateProjectRequest {
  name: string;
  research_question: string;
  domains: string[];
  intended_use: string;
  scope?: string;
  decision_criteria?: string[];
  constraints?: string[];
}

export interface UpdateProjectBriefRequest {
  action_descriptor_id: string;
  reason: string;
  research_question?: string;
  domains?: string[];
  intended_use?: string;
  scope?: string;
  decision_criteria?: string[];
  constraints?: string[];
}
