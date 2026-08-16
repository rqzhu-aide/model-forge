import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type {
  ExpectedOutputInput,
  StartSupervisedRunRequest,
  SupervisedLaunchStatus,
  SupervisedMemoryPolicy,
  SupervisedRunDetail,
  SupervisedRunSummary,
} from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/Status";
import type { Tone } from "../components/Status";
import { formatDate } from "../utils/format";
import { NotFoundPage } from "./NotFoundPage";

export const SUPERVISED_RUN_POLL_INTERVAL_MS = 4_000;

export function isTerminalSupervisedLaunchStatus(
  status: SupervisedLaunchStatus | null | undefined,
): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function supervisedRunsPollInterval(
  runs: SupervisedRunSummary[] | undefined,
): number | false {
  return runs?.some((run) => !isTerminalSupervisedLaunchStatus(run.latest_launch_status))
    ? SUPERVISED_RUN_POLL_INTERVAL_MS
    : false;
}

export const launchStatusLabels: Record<SupervisedLaunchStatus, string> = {
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function supervisedLaunchTone(
  status: SupervisedLaunchStatus | null | undefined,
): Tone {
  if (status === "succeeded") return "positive";
  if (status === "failed") return "danger";
  if (status === "running") return "information";
  return "neutral";
}

export function supervisedMethodLabel(
  identity: Record<string, unknown> | null | undefined,
): string | undefined {
  if (!identity) return undefined;
  const stableId = identity.stable_id;
  const version = identity.version;
  if (typeof stableId === "string" && stableId) {
    return typeof version === "number" ? `${stableId}, v${version}` : stableId;
  }
  return undefined;
}

function suggestedInvocationId(): string {
  return `inv-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function suggestedIdempotencyKey(invocationId: string): string {
  return `${invocationId}-${Date.now()}`;
}

export interface ExpectedOutputDraft {
  outputId: string;
  path: string;
  requiredFields: string;
}

export function buildExpectedOutputs(
  drafts: ExpectedOutputDraft[],
): { outputs: ExpectedOutputInput[] } | { problem: string } {
  const outputs: ExpectedOutputInput[] = [];
  for (const draft of drafts) {
    const outputId = draft.outputId.trim();
    const path = draft.path.trim();
    if (!outputId && !path && !draft.requiredFields.trim()) continue;
    if (!outputId || !path) {
      return {
        problem: "Each expected output needs both an output id and a path.",
      };
    }
    const requiredFields = draft.requiredFields
      .split(",")
      .map((field) => field.trim())
      .filter(Boolean);
    outputs.push({
      output_id: outputId,
      path,
      ...(requiredFields.length > 0 ? { required_fields: requiredFields } : {}),
    });
  }
  return { outputs };
}

export interface SupervisedRunFormValues {
  invocationId: string;
  idempotencyKey: string;
  role: string;
  phase: string;
  methodId: string;
  methodVersion: string;
  briefText: string;
  expectedOutputs: ExpectedOutputDraft[];
  memoryPolicy: SupervisedMemoryPolicy;
  timeoutSeconds: string;
}

export function buildSupervisedRunRequest(
  values: SupervisedRunFormValues,
): { request: StartSupervisedRunRequest } | { problem: string } {
  const invocationId = values.invocationId.trim();
  if (!invocationId) return { problem: "An invocation id is required." };
  const idempotencyKey = values.idempotencyKey.trim();
  if (!idempotencyKey) return { problem: "An idempotency key is required." };
  const role = values.role.trim();
  if (!role) return { problem: "Choose a role for this run." };
  const phase = values.phase.trim();
  if (!phase) return { problem: "A phase is required." };
  const briefText = values.briefText.trim();
  if (!briefText) return { problem: "The research brief is required." };

  const built = buildExpectedOutputs(values.expectedOutputs);
  if ("problem" in built) return built;

  const methodId = values.methodId.trim();
  let method_identity: { stable_id: string; version: number } | undefined;
  if (methodId) {
    const parsedVersion = Number(values.methodVersion);
    method_identity = {
      stable_id: methodId,
      version:
        Number.isInteger(parsedVersion) && parsedVersion >= 1 ? parsedVersion : 1,
    };
  }

  let timeout_seconds: number | undefined;
  if (values.timeoutSeconds.trim()) {
    const parsed = Number(values.timeoutSeconds);
    if (!Number.isInteger(parsed) || parsed < 1) {
      return { problem: "Timeout seconds must be a positive whole number." };
    }
    timeout_seconds = parsed;
  }

  const request: StartSupervisedRunRequest = {
    invocation_id: invocationId,
    idempotency_key: idempotencyKey,
    role,
    phase,
    brief_text: briefText,
    expected_outputs: built.outputs,
    memory_policy: values.memoryPolicy,
  };
  if (method_identity) request.method_identity = method_identity;
  if (timeout_seconds !== undefined) request.timeout_seconds = timeout_seconds;
  return { request };
}

export function SupervisedStartError({ error }: { error: unknown }) {
  const apiError = error instanceof ApiError ? error : undefined;
  if (apiError?.status === 409 && apiError.code === "SUPERVISED_RUN_LOCKED") {
    return (
      <div className="message message--warning supervised-run-lock" role="alert">
        <div>
          <strong>State lock held</strong>
          <p>{apiError.message}</p>
          {apiError.smallestCorrection ? (
            <p><span className="message__label">Next step:</span> {apiError.smallestCorrection}</p>
          ) : null}
          {apiError.code ? <code className="message__code">{apiError.code}</code> : null}
        </div>
      </div>
    );
  }
  if (apiError?.status === 409 && apiError.code === "SUPERVISED_RUN_PREFLIGHT_FAILED") {
    const failedChecks = Array.isArray(apiError.detail?.failed_checks)
      ? apiError.detail.failed_checks.filter((item): item is string => typeof item === "string")
      : [];
    return (
      <div className="message message--warning supervised-run-preflight" role="alert">
        <div>
          <strong>Preflight failed</strong>
          <p>{apiError.message}</p>
          {failedChecks.length > 0 ? (
            <ul className="preflight-failed-checks">
              {failedChecks.map((check) => <li key={check}><code>{check}</code></li>)}
            </ul>
          ) : null}
          {apiError.smallestCorrection ? (
            <p><span className="message__label">Next step:</span> {apiError.smallestCorrection}</p>
          ) : null}
          {apiError.code ? <code className="message__code">{apiError.code}</code> : null}
        </div>
      </div>
    );
  }
  return <ErrorState error={error} title="The supervised run was not started" />;
}

export function SupervisedStartSuccess({ detail }: { detail: SupervisedRunDetail }) {
  return (
    <div className="message message--positive supervised-run-started" role="status">
      <div>
        <strong>Supervised run started</strong>
        <p>Invocation <code>{detail.invocation_id}</code> is sealed and scheduled for launch.</p>
        <dl className="record-metadata">
          <div><dt>Seal</dt><dd><code>{detail.seal_id}</code></dd></div>
          <div><dt>Role</dt><dd>{detail.role}</dd></div>
          <div><dt>Sealed at</dt><dd>{formatDate(detail.sealed_at)}</dd></div>
          <div><dt>Launch records</dt><dd>{detail.launches.length}</dd></div>
        </dl>
      </div>
    </div>
  );
}

function emptyDraft(): ExpectedOutputDraft {
  return { outputId: "", path: "", requiredFields: "" };
}

export function SupervisedRunsPage() {
  const { projectId } = useParams();
  const queryClient = useQueryClient();

  const runsQuery = useQuery({
    queryKey: ["supervised-runs", projectId],
    queryFn: () => api.getSupervisedRuns(projectId as string),
    enabled: Boolean(projectId),
    refetchInterval: (query) => supervisedRunsPollInterval(query.state.data),
  });

  const rolesQuery = useQuery({
    queryKey: ["role-definitions"],
    queryFn: api.getRoleDefinitions,
  });
  const roles = rolesQuery.data?.roles ?? [];

  const [invocationId, setInvocationId] = useState(suggestedInvocationId);
  const [idempotencyKey, setIdempotencyKey] = useState(() =>
    suggestedIdempotencyKey(invocationId),
  );
  const [idempotencyTouched, setIdempotencyTouched] = useState(false);
  const [role, setRole] = useState("");
  const [phase, setPhase] = useState("P2");
  const [methodId, setMethodId] = useState("");
  const [methodVersion, setMethodVersion] = useState("");
  const [briefText, setBriefText] = useState("");
  const [expectedOutputs, setExpectedOutputs] = useState<ExpectedOutputDraft[]>([emptyDraft()]);
  const [memoryPolicy, setMemoryPolicy] = useState<SupervisedMemoryPolicy>("persistent");
  const [timeoutSeconds, setTimeoutSeconds] = useState("14400");
  const [formProblem, setFormProblem] = useState<string | undefined>(undefined);
  const [startedDetail, setStartedDetail] = useState<SupervisedRunDetail | null>(null);

  useEffect(() => {
    if (roles.length === 0) return;
    const firstRoleId = roles[0]?.role_id;
    if (!firstRoleId) return;
    setRole((current) =>
      current && roles.some((item) => item.role_id === current) ? current : firstRoleId,
    );
  }, [roles]);

  const mutation = useMutation({
    mutationFn: (request: StartSupervisedRunRequest) =>
      api.startSupervisedRun(projectId as string, request),
    onSuccess: async (detail) => {
      setStartedDetail(detail);
      setFormProblem(undefined);
      await queryClient.invalidateQueries({ queryKey: ["supervised-runs", projectId] });
    },
  });

  const changeInvocationId = (value: string) => {
    setInvocationId(value);
    if (!idempotencyTouched) setIdempotencyKey(suggestedIdempotencyKey(value));
  };

  const changeDraft = (index: number, patch: Partial<ExpectedOutputDraft>) => {
    setExpectedOutputs((current) =>
      current.map((draft, i) => (i === index ? { ...draft, ...patch } : draft)),
    );
  };

  const removeDraft = (index: number) => {
    setExpectedOutputs((current) =>
      current.length === 1 ? current : current.filter((_, i) => i !== index),
    );
  };

  const submit = () => {
    const built = buildSupervisedRunRequest({
      invocationId,
      idempotencyKey,
      role,
      phase,
      methodId,
      methodVersion,
      briefText,
      expectedOutputs,
      memoryPolicy,
      timeoutSeconds,
    });
    if ("problem" in built) {
      setFormProblem(built.problem);
      return;
    }
    setFormProblem(undefined);
    mutation.mutate(built.request);
  };

  if (!projectId) return <NotFoundPage />;

  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Supervised execution</p>
        <h1>Supervised runs</h1>
        <p>
          Sealed invocations of this project and the explicit command to start a new one.
          Nothing launches until you submit this form.
        </p>
      </header>

      <Panel
        title="New supervised run"
        eyebrow="Explicit user command"
        description="The invocation is sealed with exactly these choices and launched in the background after a preflight pass."
      >
        <form
          className="run-form"
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <div className="form-grid">
            <label className="field">
              <span>Invocation id</span>
              <input
                value={invocationId}
                onChange={(event) => changeInvocationId(event.target.value)}
                required
              />
              <small>A fresh id is suggested for each new run.</small>
            </label>
            <label className="field">
              <span>Idempotency key</span>
              <input
                value={idempotencyKey}
                onChange={(event) => {
                  setIdempotencyTouched(true);
                  setIdempotencyKey(event.target.value);
                }}
                required
              />
              <small>Replaying the same key returns the same invocation instead of launching again.</small>
            </label>
            <label className="field">
              <span>Role</span>
              {roles.length > 0 ? (
                <select value={role} onChange={(event) => setRole(event.target.value)}>
                  {roles.map((item) => (
                    <option key={item.role_id} value={item.role_id}>
                      {item.display_name} ({item.role_id})
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  value={role}
                  onChange={(event) => setRole(event.target.value)}
                  placeholder="research_lead"
                />
              )}
              <small>
                {rolesQuery.isError
                  ? "Role definitions are unavailable; type the role id instead."
                  : "One of the configured research roles."}
              </small>
            </label>
            <label className="field">
              <span>Phase</span>
              <input
                value={phase}
                onChange={(event) => setPhase(event.target.value)}
                list="supervised-phase-options"
                required
              />
              <datalist id="supervised-phase-options">
                <option value="P1" />
                <option value="P2" />
                <option value="P3" />
                <option value="P4" />
                <option value="P5" />
              </datalist>
            </label>
            <label className="field">
              <span>Method id (optional)</span>
              <input
                value={methodId}
                onChange={(event) => setMethodId(event.target.value)}
                placeholder="m_estimator"
              />
            </label>
            <label className="field">
              <span>Method version (optional)</span>
              <input
                type="number"
                min={1}
                value={methodVersion}
                onChange={(event) => setMethodVersion(event.target.value)}
                placeholder="1"
              />
            </label>
          </div>

          <label className="field field--wide field--prominent">
            <span>Research brief</span>
            <textarea
              value={briefText}
              onChange={(event) => setBriefText(event.target.value)}
              rows={5}
              required
              placeholder="State the scientific question, the boundary conditions, and the expected reasoning for this run."
            />
            <small>Sealed verbatim into the run manifest; nothing runs without it.</small>
          </label>

          <fieldset>
            <legend>Expected outputs</legend>
            <p className="field-help">
              Declare the files the run must produce under its outputs directory. Required
              fields are comma-separated.
            </p>
            {expectedOutputs.map((draft, index) => (
              <div className="expected-output-row" key={index}>
                <input
                  aria-label={`Expected output ${index + 1} id`}
                  placeholder="output_id"
                  value={draft.outputId}
                  onChange={(event) => changeDraft(index, { outputId: event.target.value })}
                />
                <input
                  aria-label={`Expected output ${index + 1} path`}
                  placeholder="relative/path"
                  value={draft.path}
                  onChange={(event) => changeDraft(index, { path: event.target.value })}
                />
                <input
                  aria-label={`Expected output ${index + 1} required fields`}
                  placeholder="field_a, field_b"
                  value={draft.requiredFields}
                  onChange={(event) => changeDraft(index, { requiredFields: event.target.value })}
                />
                <button
                  type="button"
                  className="button button--quiet button--small"
                  onClick={() => removeDraft(index)}
                  disabled={expectedOutputs.length === 1}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              className="button button--quiet button--small"
              onClick={() => setExpectedOutputs((current) => [...current, emptyDraft()])}
            >
              Add expected output
            </button>
          </fieldset>

          <div className="form-grid">
            <label className="field">
              <span>Memory policy</span>
              <select
                value={memoryPolicy}
                onChange={(event) => setMemoryPolicy(event.target.value as SupervisedMemoryPolicy)}
              >
                <option value="persistent">persistent</option>
                <option value="ephemeral">ephemeral</option>
                <option value="read_only">read_only</option>
              </select>
            </label>
            <label className="field">
              <span>Timeout seconds</span>
              <input
                type="number"
                min={1}
                value={timeoutSeconds}
                onChange={(event) => setTimeoutSeconds(event.target.value)}
              />
              <small>
                Default: 4 hours (long studies need well over 20 minutes).
                The launcher enforces this limit.
              </small>
            </label>
          </div>

          <div className="form-actions">
            <button
              type="submit"
              className="button button--primary"
              disabled={mutation.isPending}
            >
              {mutation.isPending ? "Starting run..." : "Start supervised run"}
            </button>
          </div>

          {formProblem ? (
            <div className="message message--error" role="alert">
              <div><strong>Check the form</strong><p>{formProblem}</p></div>
            </div>
          ) : null}
          {mutation.error ? <SupervisedStartError error={mutation.error} /> : null}
          {startedDetail ? <SupervisedStartSuccess detail={startedDetail} /> : null}
        </form>
      </Panel>

      <Panel
        title="Sealed invocations"
        eyebrow="Durable execution state"
        description="The list refreshes automatically while any invocation is still running."
      >
        {runsQuery.isLoading ? <LoadingState label="Loading supervised runs..." /> : null}
        {runsQuery.error ? (
          <ErrorState error={runsQuery.error} title="Supervised runs are unavailable" />
        ) : null}
        {runsQuery.data && runsQuery.data.length === 0 ? (
          <EmptyState title="No supervised runs">
            <p>This project has no sealed invocations yet. Start one with the form above.</p>
          </EmptyState>
        ) : null}
        {runsQuery.data && runsQuery.data.length > 0 ? (
          <ul className="run-list supervised-run-list">
            {runsQuery.data.map((run) => {
              const methodLabel = supervisedMethodLabel(run.method_identity);
              return (
                <li key={run.invocation_id}>
                  <div className="run-list__heading">
                    <Link
                      to={`/projects/${encodeURIComponent(projectId)}/supervised/${encodeURIComponent(run.invocation_id)}`}
                      className="run-list__link"
                    >
                      <code>{run.invocation_id}</code>
                    </Link>
                    <StatusPill tone={supervisedLaunchTone(run.latest_launch_status)}>
                      {run.latest_launch_status
                        ? launchStatusLabels[run.latest_launch_status]
                        : "Not launched"}
                    </StatusPill>
                  </div>
                  {run.promoted ? (
                    <div className="run-list__markers" aria-label="Supervised run markers">
                      <span>Promoted</span>
                    </div>
                  ) : null}
                  <p>
                    <span>{run.role}</span>
                    {run.phase ? <span>{run.phase}</span> : null}
                    {methodLabel ? <span>{methodLabel}</span> : null}
                    {run.validation_verdict ? (
                      <span>
                        <StatusPill tone={run.validation_verdict === "pass" ? "positive" : "danger"}>
                          {run.validation_verdict === "pass" ? "Validation passed" : "Validation failed"}
                        </StatusPill>
                      </span>
                    ) : null}
                  </p>
                  <small>
                    Memory {run.memory_policy ?? "not recorded"} · Sealed {formatDate(run.sealed_at)}
                  </small>
                </li>
              );
            })}
          </ul>
        ) : null}
      </Panel>
    </div>
  );
}
