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
  | "cancelled";

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
  | "update_project_brief";

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
  projection: ProjectionStamp;
  empty_state_message?: string;
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
