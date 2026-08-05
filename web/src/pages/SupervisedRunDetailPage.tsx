import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type {
  SupervisedLaunchRecord,
  SupervisedPromotionRecord,
  SupervisedRunDetail,
} from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/Status";
import type { Tone } from "../components/Status";
import { formatDate, sentenceCase, shortDigest } from "../utils/format";
import { NotFoundPage } from "./NotFoundPage";
import {
  SUPERVISED_RUN_POLL_INTERVAL_MS,
  isTerminalSupervisedLaunchStatus,
  launchStatusLabels,
  supervisedLaunchTone,
  supervisedMethodLabel,
} from "./SupervisedRunsPage";

// ---------------------------------------------------------------------------
// Durable-state derivation helpers (WP-F3b)
// ---------------------------------------------------------------------------

export function supervisedRunDetailPollInterval(
  detail: SupervisedRunDetail | undefined,
): number | false {
  if (!detail) return false;
  // Never-launched is non-terminal (a launch can start at any time),
  // matching the list page's convention for null latest_launch_status.
  if (detail.launches.length === 0) return SUPERVISED_RUN_POLL_INTERVAL_MS;
  return detail.launches.some((launch) => !isTerminalSupervisedLaunchStatus(launch.status))
    ? SUPERVISED_RUN_POLL_INTERVAL_MS
    : false;
}

export function checkTone(status: string | undefined): Tone {
  if (status === "pass") return "positive";
  if (status === "fail") return "danger";
  if (status === "warning") return "warning";
  return "neutral";
}

export function checkStatusLabel(status: string | undefined): string {
  if (status === "pass") return "Pass";
  if (status === "fail") return "Fail";
  if (status === "warning") return "Warning";
  return status ? sentenceCase(status) : "Not recorded";
}

export function formatElapsedTime(
  launchedAt: string,
  closedAt: string | null | undefined,
): string | undefined {
  const start = new Date(launchedAt).getTime();
  const end = closedAt ? new Date(closedAt).getTime() : Date.now();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return undefined;
  const totalSeconds = Math.round((end - start) / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function smallestSafeNextAction(detail: SupervisedRunDetail): string {
  const latest = detail.launches[detail.launches.length - 1];
  if (!latest) return "Start this run from the list page";
  if (latest.status === "running") return "Wait or cancel";
  if (latest.status === "failed" || latest.status === "cancelled") {
    return "Investigate the logs, then start a new invocation";
  }
  if (detail.validation?.verdict === "fail") {
    return "Review the failed checks; the run changed no state";
  }
  if (detail.validation?.verdict === "pass") {
    return detail.promotions.length > 0
      ? "State promoted; the next run sees it"
      : "Outputs valid; policy promotes nothing";
  }
  return "Review the run output before starting a new invocation";
}

export function promotionTargetNames(promotion: SupervisedPromotionRecord): string[] {
  const names = new Set<string>([
    ...Object.keys(promotion.before_digest),
    ...Object.keys(promotion.after_digest),
    ...Object.keys(promotion.backup_paths),
  ]);
  return [...names].sort();
}

// ---------------------------------------------------------------------------
// Small coercion helpers for the loose manifest records
// ---------------------------------------------------------------------------

function stringValue(
  record: Record<string, unknown> | null | undefined,
  key: string,
): string | undefined {
  const value = record?.[key];
  return typeof value === "string" && value ? value : undefined;
}

function digestText(value: unknown): string {
  return typeof value === "string" && value ? shortDigest(value) : "—";
}

function expectedOutputFields(entry: Record<string, unknown>): {
  outputId: string;
  path: string;
  requiredFields: string[];
} {
  const outputId = stringValue(entry, "output_id") ?? "";
  const path =
    stringValue(entry, "path") ?? stringValue(entry, "relative_path") ?? "";
  const rawFields = Array.isArray(entry.required_fields) ? entry.required_fields : [];
  const requiredFields = rawFields.filter((field): field is string => typeof field === "string");
  return { outputId, path, requiredFields };
}

// ---------------------------------------------------------------------------
// Panels, in lifecycle order
// ---------------------------------------------------------------------------

export function SealedBasisPanel({ detail }: { detail: SupervisedRunDetail }) {
  const manifest = detail.manifest;
  if (!manifest) {
    return (
      <div className="message message--neutral" role="status">
        <div>
          <strong>Sealed basis unavailable</strong>
          <p>
            {detail.manifest_note ??
              "The stored manifest JSON is not readable for this invocation."}
          </p>
        </div>
      </div>
    );
  }
  const methodLabel = supervisedMethodLabel(manifest.method_identity);
  const memory = manifest.memory_snapshot;
  const session = manifest.session_snapshot;
  const hermes = manifest.hermes;
  const memoryIdentity = stringValue(memory, "identity");
  const memorySource = stringValue(memory, "source");
  const sessionProcedure = stringValue(session, "procedure");
  const sessionSha = stringValue(session, "sha256");
  const sessionSource = stringValue(session, "source");
  const sessionQuiescent =
    typeof session?.quiescent === "boolean" ? (session.quiescent ? "yes" : "no") : undefined;
  const hermesExecutable = stringValue(hermes, "executable");
  const hermesVersion = stringValue(hermes, "version");
  const assetDigests = Object.entries(manifest.role_asset_digests);

  return (
    <>
      <dl className="record-metadata">
        <div><dt>Role</dt><dd>{manifest.role}</dd></div>
        <div><dt>Phase</dt><dd>{manifest.phase}</dd></div>
        <div>
          <dt>Method identity</dt>
          <dd>{methodLabel ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Memory policy</dt>
          <dd>{stringValue(memory, "policy") ?? "Not recorded"}</dd>
        </div>
        <div>
          <dt>Memory snapshot</dt>
          <dd>
            {memoryIdentity ? <code>{memoryIdentity}</code> : "Not recorded"}
            {memorySource ? (
              <small className="record-metadata__sub">source: {memorySource}</small>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Session snapshot</dt>
          <dd>
            {sessionProcedure ? (
              <>
                <code>{sessionProcedure}</code>
                {sessionSha ? (
                  <small className="record-metadata__sub">
                    sha256 {shortDigest(sessionSha)} · quiescent {sessionQuiescent ?? "not recorded"}
                  </small>
                ) : null}
              </>
            ) : (
              "Not recorded"
            )}
            {sessionSource ? (
              <small className="record-metadata__sub">source: {sessionSource}</small>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Hermes executable</dt>
          <dd>{hermesExecutable ? <code>{hermesExecutable}</code> : "Not recorded"}</dd>
        </div>
        <div>
          <dt>Hermes version</dt>
          <dd>{hermesVersion ?? "Not recorded"}</dd>
        </div>
      </dl>

      <h3 className="panel-subheading">Expected outputs</h3>
      {manifest.expected_outputs.length === 0 ? (
        <p className="muted-note">No expected outputs were declared.</p>
      ) : (
        <ul className="expected-outputs-list">
          {manifest.expected_outputs.map((entry) => {
            const { outputId, path, requiredFields } = expectedOutputFields(entry);
            return (
              <li key={`${outputId}-${path}`}>
                <code>{outputId || "unnamed"}</code>
                <span>{path}</span>
                {requiredFields.length > 0 ? (
                  <small>Required fields: {requiredFields.join(", ")}</small>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      <h3 className="panel-subheading">Role asset digests</h3>
      {assetDigests.length === 0 ? (
        <p className="muted-note">No role asset digests were recorded in the manifest.</p>
      ) : assetDigests.length > 4 ? (
        <details className="asset-digests">
          <summary>{assetDigests.length} role asset digests</summary>
          <ul className="asset-digest-list">
            {assetDigests.map(([relative, digest]) => (
              <li key={relative}>
                <code>{relative}</code>
                <code className="asset-digest-list__digest" title={digest}>
                  {shortDigest(digest)}
                </code>
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <ul className="asset-digest-list">
          {assetDigests.map(([relative, digest]) => (
            <li key={relative}>
              <code>{relative}</code>
              <code className="asset-digest-list__digest" title={digest}>
                {shortDigest(digest)}
              </code>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function PreflightPanel({ detail }: { detail: SupervisedRunDetail }) {
  const report = detail.preflight_report;
  if (!report) {
    return (
      <div className="message message--neutral preflight-note" role="status">
        <div>
          <strong>No preflight report</strong>
          <p>
            {detail.preflight_note ??
              "This invocation was sealed but never started, so no preflight was recorded."}
          </p>
        </div>
      </div>
    );
  }
  return (
    <>
      <div className="verdict-line">
        <StatusPill tone={report.verdict === "pass" ? "positive" : "danger"}>
          {report.verdict === "pass" ? "Preflight passed" : "Preflight failed"}
        </StatusPill>
        <span>Reported {formatDate(report.created_at)}</span>
      </div>
      <ul className="checks-list">
        {report.checks.map((check) => (
          <li
            key={check.name}
            className={check.status === "fail" ? "checks-list__item checks-list__item--fail" : "checks-list__item"}
            data-status={check.status}
          >
            <span className="checks-list__name"><code>{check.name}</code></span>
            <StatusPill tone={checkTone(check.status)}>{checkStatusLabel(check.status)}</StatusPill>
            <span className="checks-list__detail">{check.detail}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

export function LaunchRecordsPanel({ detail }: { detail: SupervisedRunDetail }) {
  if (detail.launches.length === 0) {
    return (
      <EmptyState title="Not launched">
        <p>
          This invocation is sealed but has no launch record yet. Start it from the supervised
          runs list page.
        </p>
      </EmptyState>
    );
  }
  return (
    <ul className="launch-records">
      {detail.launches.map((launch) => (
        <li key={launch.launch_id} className="launch-record">
          <div className="launch-record__heading">
            <code>{launch.launch_id}</code>
            <StatusPill tone={supervisedLaunchTone(launch.status)}>
              {launchStatusLabels[launch.status]}
            </StatusPill>
          </div>
          <dl className="record-metadata">
            <div><dt>Exit code</dt><dd>{launch.exit_code ?? "—"}</dd></div>
            <div>
              <dt>External execution id</dt>
              <dd>
                {launch.external_execution_id ? (
                  <code className="durable-id" title={launch.external_execution_id}>
                    {launch.external_execution_id}
                  </code>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div>
              <dt>Task brief sha256</dt>
              <dd>
                {launch.task_brief_sha256 ? (
                  <code title={launch.task_brief_sha256}>{shortDigest(launch.task_brief_sha256)}</code>
                ) : (
                  "—"
                )}
              </dd>
            </div>
            <div><dt>Launched at</dt><dd>{formatDate(launch.launched_at)}</dd></div>
            <div><dt>Closed at</dt><dd>{launch.closed_at ? formatDate(launch.closed_at) : "—"}</dd></div>
            <div>
              <dt>Elapsed</dt>
              <dd>{formatElapsedTime(launch.launched_at, launch.closed_at) ?? "—"}</dd>
            </div>
          </dl>
        </li>
      ))}
    </ul>
  );
}

export function ClosurePanel({ detail }: { detail: SupervisedRunDetail }) {
  const validation = detail.validation;
  return (
    <>
      <h3 className="panel-subheading">Output validation</h3>
      {validation ? (
        <>
          <div className="verdict-line">
            <StatusPill tone={validation.verdict === "pass" ? "positive" : "danger"}>
              {validation.verdict === "pass" ? "Validation passed" : "Validation failed"}
            </StatusPill>
            <span>
              Validated {formatDate(validation.validated_at)} · Launch{" "}
              <code>{validation.launch_id}</code>
            </span>
          </div>
          <ul className="checks-list">
            {validation.checks.map((check) => (
              <li
                key={check.name}
                className={check.status === "fail" ? "checks-list__item checks-list__item--fail" : "checks-list__item"}
                data-status={check.status}
              >
                <span className="checks-list__name"><code>{check.name}</code></span>
                <StatusPill tone={checkTone(check.status)}>{checkStatusLabel(check.status)}</StatusPill>
                <span className="checks-list__detail">{check.detail}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted-note">No validation report was recorded for this invocation.</p>
      )}

      <h3 className="panel-subheading">Promotion history</h3>
      {detail.promotions.length === 0 ? (
        <EmptyState title="Nothing promoted">
          <p>This invocation produced no promotion records, so no project state was changed by it.</p>
        </EmptyState>
      ) : (
        <ul className="promotion-records">
          {detail.promotions.map((promotion) => (
            <li key={promotion.record_id} className="promotion-record">
              <div className="promotion-record__heading">
                <code>{promotion.record_id}</code>
                <StatusPill tone={promotion.status === "succeeded" ? "positive" : "danger"}>
                  {promotion.status === "succeeded" ? "Promoted" : "Failed"}
                </StatusPill>
              </div>
              <dl className="record-metadata">
                <div><dt>Promoted at</dt><dd>{formatDate(promotion.promoted_at)}</dd></div>
              </dl>
              <ul className="promotion-targets">
                {promotionTargetNames(promotion).map((name) => {
                  const backupPath = stringValue(promotion.backup_paths, name);
                  return (
                    <li key={name} className="promotion-target">
                      <code className="promotion-target__name">{name}</code>
                      <span
                        className="promotion-target__digest"
                        title={`before ${String(promotion.before_digest[name] ?? "")} → after ${String(promotion.after_digest[name] ?? "")}`}
                      >
                        <span className="promotion-target__before">{digestText(promotion.before_digest[name])}</span>
                        <span aria-hidden="true"> → </span>
                        <span className="promotion-target__after">{digestText(promotion.after_digest[name])}</span>
                      </span>
                      <span className="promotion-target__backup" title={backupPath}>
                        {backupPath ? `Backup: ${backupPath}` : "Backup: not recorded"}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function SupervisedCancelError({ error }: { error: unknown }) {
  const apiError = error instanceof ApiError && error.status === 409 ? error : undefined;
  if (!apiError) {
    return <ErrorState error={error} title="The run was not cancelled" />;
  }
  return (
    <div className="message message--warning cancel-error" role="alert">
      <div>
        <strong>Not cancelled</strong>
        <p>{apiError.message}</p>
        {apiError.smallestCorrection ? (
          <p><span className="message__label">Next step:</span> {apiError.smallestCorrection}</p>
        ) : null}
        {apiError.code ? <code className="message__code">{apiError.code}</code> : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function SupervisedRunDetailPage() {
  const { projectId, invocationId } = useParams();
  const queryClient = useQueryClient();

  const detailQuery = useQuery({
    queryKey: ["supervised-run", projectId, invocationId],
    queryFn: () => api.getSupervisedRun(projectId as string, invocationId as string),
    enabled: Boolean(projectId && invocationId),
    refetchInterval: (query) => supervisedRunDetailPollInterval(query.state.data),
  });

  const cancelMutation = useMutation({
    mutationFn: () => {
      if (!projectId || !invocationId) {
        throw new Error("No cancel command is available for this invocation.");
      }
      return api.cancelSupervisedRun(projectId, invocationId);
    },
    onSuccess: async (updated) => {
      if (!projectId || !invocationId) return;
      queryClient.setQueryData(["supervised-run", projectId, invocationId], updated);
      await queryClient.invalidateQueries({
        queryKey: ["supervised-run", projectId, invocationId],
      });
      await queryClient.invalidateQueries({ queryKey: ["supervised-runs", projectId] });
    },
  });

  if (!projectId || !invocationId) return <NotFoundPage />;
  if (detailQuery.isLoading) return <LoadingState label="Loading supervised run detail..." />;
  if (detailQuery.error) {
    return <ErrorState error={detailQuery.error} title="Supervised run detail is unavailable" />;
  }
  if (!detailQuery.data) return <NotFoundPage />;

  const detail = detailQuery.data;
  const latestLaunch: SupervisedLaunchRecord | undefined =
    detail.launches[detail.launches.length - 1];
  const canCancel = latestLaunch?.status === "running";

  return (
    <div className="page-stack">
      <header className="page-header run-heading">
        <div>
          <p className="eyebrow">Supervised execution</p>
          <h1>Supervised run</h1>
          <p><code>{detail.invocation_id}</code></p>
        </div>
        <div className="page-header__actions">
          <Link
            to={`/projects/${encodeURIComponent(projectId)}/supervised`}
            className="button button--quiet"
          >
            Back to supervised runs
          </Link>
        </div>
      </header>

      <p className="next-action">
        <span className="message__label">Next:</span> {smallestSafeNextAction(detail)}
      </p>

      <Panel
        title="Sealed basis"
        eyebrow="Immutable seal manifest"
        description="The exact role, method, state snapshots, and tool identities this invocation was sealed with."
      >
        <SealedBasisPanel detail={detail} />
      </Panel>

      <Panel
        title="Preflight"
        eyebrow="Launch gate"
        description="The named checks the launcher ran before the first process started."
      >
        <PreflightPanel detail={detail} />
      </Panel>

      <Panel
        title="Launches"
        eyebrow="Durable launch records"
        description="The detail refreshes automatically while a launch is still running."
        actions={
          canCancel ? (
            <button
              type="button"
              className="button button--danger"
              disabled={cancelMutation.isPending}
              onClick={() => cancelMutation.mutate()}
            >
              {cancelMutation.isPending ? "Cancelling..." : "Cancel this run"}
            </button>
          ) : undefined
        }
      >
        {cancelMutation.error ? <SupervisedCancelError error={cancelMutation.error} /> : null}
        <LaunchRecordsPanel detail={detail} />
      </Panel>

      <Panel
        title="Closure"
        eyebrow="Validation and promotion"
        description="What the run produced, what passed or failed validation, and which project state was promoted."
      >
        <ClosurePanel detail={detail} />
      </Panel>
    </div>
  );
}
