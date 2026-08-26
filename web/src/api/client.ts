import type {
  ActionDescriptor,
  ConfigurationHealthView,
  CorrectionCommandInput,
  CorrectionPreview,
  CreateProjectRequest,
  MethodRow,
  PhaseId,
  PhaseView,
  ProfileConfigurationView,
  ProjectBriefView,
  ProjectOverview,
  ProjectSummary,
  ProvisionResultView,
  ProvisionRoleRequest,
  RoleDefinitionCatalogView,
  RoleDefinitionView,
  RoleHealthReportView,
  RunDetail,
  RunEvent,
  RunSummary,
  StartRunRequest,
  StartSupervisedRunRequest,
  SupervisedRunDetail,
  SupervisedRunLogs,
  SupervisedRunSummary,
  SystemSettingsView,
  UpdateProjectBriefRequest,
} from "./types";

const API_ROOT = "/api/v1";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | undefined;
  readonly smallestCorrection: string | undefined;
  readonly objectRefs: string[] | undefined;
  readonly detail: Record<string, unknown> | undefined;

  constructor(
    message: string,
    status: number,
    code?: string,
    smallestCorrection?: string,
    objectRefs?: string[],
    detail?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.smallestCorrection = smallestCorrection;
    this.objectRefs = objectRefs;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let payload: {
      researcher_message?: string;
      message?: string;
      code?: string;
      smallest_correction?: string;
      object_refs?: string[];
      detail?: Record<string, unknown>;
    } = {};
    try {
      payload = (await response.json()) as typeof payload;
    } catch {
      // The transport may fail before a structured command error exists.
    }
    throw new ApiError(
      payload.researcher_message ?? payload.message ?? `Request failed (${response.status}).`,
      response.status,
      payload.code,
      payload.smallest_correction,
      payload.object_refs,
      payload.detail,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function requestText(path: string): Promise<string> {
  // Artifact content may be JSON or plain text; discriminate by content
  // type and pretty-print JSON payloads (FP-7.5: route artifact fetches
  // through the client instead of raw fetch in components).
  const response = await fetch(`${API_ROOT}${path}`, {
    headers: { Accept: "application/json, text/plain, */*" },
  });
  if (!response.ok) {
    throw new ApiError(`Request failed (${response.status}).`, response.status);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const data = await response.json();
    return typeof data === "string" ? data : JSON.stringify(data, null, 2);
  }
  return response.text();
}

function commandRequest<T>(
  path: string,
  method: "POST" | "PATCH",
  body: unknown,
): Promise<T> {
  // The key is created once for this command invocation. A transport retry must
  // reuse this RequestInit; a later researcher command calls this function again.
  const init: RequestInit = {
    method,
    headers: { "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify(body),
  };
  return request<T>(path, init);
}

function queryString(values: Record<string, string | undefined>): string {
  const params = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export const api = {
  listProjects: () => request<ProjectSummary[]>("/projects"),

  createProject: (input: CreateProjectRequest) =>
    commandRequest<ProjectSummary>("/projects", "POST", input),

  getProjectOverview: (projectId: string) =>
    request<ProjectOverview>(`/projects/${encodeURIComponent(projectId)}/overview`),

  getProjectBrief: (projectId: string) =>
    request<ProjectBriefView>(`/projects/${encodeURIComponent(projectId)}/brief`),

  updateProjectBrief: (projectId: string, input: UpdateProjectBriefRequest) =>
    commandRequest<ProjectBriefView>(
      `/projects/${encodeURIComponent(projectId)}/brief`,
      "PATCH",
      input,
    ),

  getSystemSettings: () => request<SystemSettingsView>("/system/settings"),

  getPhaseView: (
    projectId: string,
    phaseId: PhaseId,
    selection?: { mode?: string; methodId?: string },
  ) =>
    request<PhaseView>(
      `/projects/${encodeURIComponent(projectId)}/phases/${phaseId}${queryString({
        mode: selection?.mode,
        method_id: selection?.methodId,
      })}`,
    ),

  listMethods: (projectId: string) =>
    request<MethodRow[]>(`/projects/${encodeURIComponent(projectId)}/methods`),

  changeMethodLifecycle: (
    projectId: string,
    methodId: string,
    action: ActionDescriptor,
    reason: string,
  ) =>
    commandRequest<void>(
      `/projects/${encodeURIComponent(projectId)}/methods/${encodeURIComponent(methodId)}/lifecycle`,
      "POST",
      { action_descriptor_id: action.descriptor_id, reason },
    ),

  listRuns: (projectId: string, phase?: PhaseId) =>
    request<RunSummary[]>(
      `/projects/${encodeURIComponent(projectId)}/runs${queryString({ phase })}`,
    ),

  startRun: (projectId: string, input: StartRunRequest) =>
    commandRequest<RunDetail>(`/projects/${encodeURIComponent(projectId)}/runs`, "POST", input),

  getRun: (projectId: string, runId: string) =>
    request<RunDetail>(
      `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}`,
    ),

  getArtifactContent: (projectId: string, artifactId: string) =>
    requestText(
      `/projects/${encodeURIComponent(projectId)}/artifacts/${encodeURIComponent(artifactId)}`,
    ),

  listRunEvents: (projectId: string, runId: string, afterSequence = 0) =>
    request<RunEvent[]>(
      `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/events${queryString({
        after_sequence: String(afterSequence),
      })}`,
    ),

  runEventStreamUrl: (projectId: string, runId: string, afterSequence = 0) =>
    `${API_ROOT}/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/events/stream${queryString({
      after_sequence: String(afterSequence),
    })}`,

  cancelRun: (projectId: string, runId: string, action: ActionDescriptor, reason: string) =>
    commandRequest<RunDetail>(
      `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/cancel`,
      "POST",
      { action_descriptor_id: action.descriptor_id, reason },
    ),

  // Read-only dry run of the normalize transformation lane (K-1b). Plain POST:
  // the preview writes no state and requires no idempotency key. Its
  // output_scope is also the scope source for every correction command.
  previewRunCorrection: (projectId: string, runId: string, transformationCodes: string[] = []) =>
    request<CorrectionPreview>(
      `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/corrections/preview`,
      { method: "POST", body: JSON.stringify({ transformation_codes: transformationCodes }) },
    ),

  requestRunCorrection: (
    projectId: string,
    runId: string,
    action: ActionDescriptor,
    input: CorrectionCommandInput,
  ) =>
    commandRequest<RunDetail>(
      `/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}/corrections`,
      "POST",
      { action_descriptor_id: action.descriptor_id, ...input },
    ),

  getProfiles: (projectId: string) =>
    request<ProfileConfigurationView>(
      `/projects/${encodeURIComponent(projectId)}/configuration/profiles`,
    ),

  saveProfile: (projectId: string, roleId: string, profileId: string, actionId: string) =>
    commandRequest<ProfileConfigurationView>(
      `/projects/${encodeURIComponent(projectId)}/configuration/profiles/${encodeURIComponent(roleId)}`,
      "PATCH",
      { profile_id: profileId, action_descriptor_id: actionId },
    ),

  installSkill: (
    projectId: string,
    roleId: string,
    skillId: string,
    actionId: string,
  ) =>
    commandRequest<ProfileConfigurationView>(
      `/projects/${encodeURIComponent(projectId)}/configuration/profiles/${encodeURIComponent(roleId)}/skills/${encodeURIComponent(skillId)}/install`,
      "POST",
      { action_descriptor_id: actionId },
    ),

  getRoleDefinitions: () =>
    request<RoleDefinitionCatalogView>("/configuration/roles"),

  getRoleDefinition: (roleId: string) =>
    request<RoleDefinitionView>(`/configuration/roles/${encodeURIComponent(roleId)}`),

  getConfigurationHealth: () =>
    request<ConfigurationHealthView>("/configuration/health"),

  getRoleHealth: (roleId: string) =>
    request<RoleHealthReportView>(`/configuration/roles/${encodeURIComponent(roleId)}/health`),

  provisionRole: (roleId: string, input: ProvisionRoleRequest) =>
    commandRequest<ProvisionResultView>(
      `/configuration/roles/${encodeURIComponent(roleId)}/provision`,
      "POST",
      input,
    ),

  getSupervisedRuns: (projectId: string) =>
    request<SupervisedRunSummary[]>(
      `/projects/${encodeURIComponent(projectId)}/supervised-runs`,
    ),

  getSupervisedRun: (projectId: string, invocationId: string) =>
    request<SupervisedRunDetail>(
      `/projects/${encodeURIComponent(projectId)}/supervised-runs/${encodeURIComponent(invocationId)}`,
    ),

  getSupervisedRunLogs: (
    projectId: string,
    invocationId: string,
    tailMaxBytes = 65536,
  ) =>
    request<SupervisedRunLogs>(
      `/projects/${encodeURIComponent(projectId)}/supervised-runs/${encodeURIComponent(invocationId)}/logs?tail_max_bytes=${tailMaxBytes}`,
    ),

  startSupervisedRun: (projectId: string, input: StartSupervisedRunRequest) =>
    commandRequest<SupervisedRunDetail>(
      `/projects/${encodeURIComponent(projectId)}/supervised-runs`,
      "POST",
      input,
    ),

  cancelSupervisedRun: (projectId: string, invocationId: string) =>
    commandRequest<SupervisedRunDetail>(
      `/projects/${encodeURIComponent(projectId)}/supervised-runs/${encodeURIComponent(invocationId)}/cancel`,
      "POST",
      {},
    ),
};
