import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { FindingGroup, RunDetail, RunLifecycleProjection, RunLifecycleState } from "../api/types";
import { ConfirmActionDialog } from "../components/ConfirmActionDialog";
import { CorrectionControls, correctionStateNotice } from "../components/CorrectionControls";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { FrozenBasis, RunEventList, RunTimeline, runIsStale } from "../components/RunTimeline";
import { StatusPill } from "../components/Status";
import { useRunEvents } from "../hooks/useRunEvents";
import { useTerminalRunRefresh } from "../hooks/useTerminalRunRefresh";
import { formatDate, isRunActive, sentenceCase } from "../utils/format";
import { NotFoundPage } from "./NotFoundPage";

export type RecoverySummary = RunLifecycleProjection["recovery_summary"];

function recoverySummaryOf(run: RunDetail): RecoverySummary | undefined {
  return run.lifecycle_projection?.recovery_summary;
}

function findingClassTone(
  findingClass: FindingGroup["finding_class"],
): "danger" | "warning" | "neutral" {
  if (
    findingClass === "operational_failure" ||
    findingClass === "integrity_blocker" ||
    findingClass === "scientific_claim_blocker"
  ) {
    return "danger";
  }
  if (findingClass === "correctable_contract_error" || findingClass === "scientific_attention") {
    return "warning";
  }
  return "neutral";
}

function recoveryGuidance(run: RunDetail): string | undefined {
  const recovery = recoverySummaryOf(run);
  if (recovery === "needs_output_correction") {
    return "The recorded output checks must be corrected before this work can become formal project state. Your current project record was not changed. Use the correction controls on this page to re-check or repair the sealed outputs; a full rerun remains available from the phase page.";
  }
  if (recovery === "correction_exhausted") {
    return "The bounded correction attempts did not produce passing outputs. Return to the phase to configure a full rerun; every correction attempt remains recorded on this run.";
  }
  if (recovery === "failed") {
    return "Inspect the terminal reason and progress events, then return to the phase to configure a corrected rerun. The failed attempt did not replace formal project state.";
  }
  if (recovery === "rejected") {
    return "Review the validation report and correct the stated contract or scientific output before starting a new run. Material that fails integrity checks cannot become formal project state.";
  }
  if (run.state === "failed") {
    return "Inspect the terminal reason and progress events, then return to the phase to configure a corrected rerun. The failed attempt did not replace formal project state.";
  }
  if (run.state === "rejected") {
    return "Review the validation report and correct the stated contract or scientific output before starting a new run. Rejected output was not published.";
  }
  if (recovery === "conflicted" || run.state === "conflicted") {
    return "Compare this run's frozen basis with the current phase record. If the current basis should be used, return to the phase and start a new run with that context.";
  }
  if (recovery === "cancelled" || run.state === "cancelled") {
    return "The run stopped without changing the current formal result. Return to the phase when you want to revise the instructions or start another run.";
  }
  return undefined;
}

export function terminalReasonPresentation(
  state: RunLifecycleState,
  recoverySummary?: RecoverySummary,
): {
  className: string;
  role: "alert" | "status";
} {
  // A completed Hermes exit with correctable output checks is NOT an execution
  // failure — never present it as an error alert (HV-3.4).
  if (recoverySummary === "needs_output_correction") {
    return { className: "message message--warning", role: "status" };
  }
  if (recoverySummary === "failed" || recoverySummary === "rejected") {
    return { className: "message message--error", role: "alert" };
  }
  if (state === "failed" || state === "rejected") {
    return { className: "message message--error", role: "alert" };
  }
  if (recoverySummary === "conflicted" || state === "conflicted") {
    return { className: "message message--warning", role: "status" };
  }
  return { className: "message message--neutral", role: "status" };
}

export async function invalidateRunCommandDependents(
  queryClient: QueryClient,
  projectId: string,
  phase: RunDetail["phase"],
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["phase", projectId, phase] }),
    queryClient.invalidateQueries({ queryKey: ["overview", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["profiles"] }),
  ]);
}

export async function invalidateCancellationRequestDependents(
  queryClient: QueryClient,
  projectId: string,
  phase: RunDetail["phase"],
): Promise<void> {
  return invalidateRunCommandDependents(queryClient, projectId, phase);
}

export function RunPage() {
  const { projectId, runId } = useParams();
  const queryClient = useQueryClient();
  const [confirmCancel, setConfirmCancel] = useState(false);

  const runQuery = useQuery({
    queryKey: ["run", projectId, runId],
    queryFn: () => api.getRun(projectId as string, runId as string),
    enabled: Boolean(projectId && runId),
    refetchInterval: (query) => {
      const run = query.state.data;
      return run && isRunActive(run.state, run.lifecycle_projection?.recovery_summary) ? 4_000 : false;
    },
  });
  const eventsQuery = useRunEvents(projectId ?? "", runQuery.data);
  useTerminalRunRefresh(projectId ?? "", runQuery.data);
  const cancelAction = runQuery.data?.actions.find((action) => action.action_type === "cancel_run");

  const cancelMutation = useMutation({
    mutationFn: (reason: string) => {
      if (!projectId || !runId || !cancelAction) throw new Error("No cancel command is available.");
      return api.cancelRun(projectId, runId, cancelAction, reason);
    },
    onSuccess: async (run) => {
      setConfirmCancel(false);
      if (!projectId) return;
      queryClient.setQueryData(["run", projectId, runId], run);
      await invalidateCancellationRequestDependents(queryClient, projectId, run.phase);
    },
  });

  if (!projectId || !runId) return <NotFoundPage />;
  if (runQuery.isLoading) return <LoadingState label="Loading run state..." />;
  if (runQuery.error) return <ErrorState error={runQuery.error} title="Run state is unavailable" />;
  if (!runQuery.data) return <NotFoundPage />;

  const run = runQuery.data;
  const projection = run.lifecycle_projection;
  const recovery = recoverySummaryOf(run);
  const guidance = recoveryGuidance(run);
  const correctionCount = projection
    ? Math.max(projection.correctable_finding_count, projection.blocking_finding_count)
    : 0;
  const stale = runIsStale(run);
  const cancelReasonId = `cancel-run-disabled-${run.run_id}`;
  const terminalPresentation = terminalReasonPresentation(run.state, recovery);
  const correctionNotice = correctionStateNotice(run);

  const handleCorrectionSettled = async (updated: RunDetail) => {
    queryClient.setQueryData(["run", projectId, runId], updated);
    if (!projectId) return;
    await invalidateRunCommandDependents(queryClient, projectId, updated.phase);
  };

  return (
    <div className="page-stack">
      <header className="page-header run-heading">
        <div>
          <p className="eyebrow">Controlled research operation</p>
          <h1>{run.phase} run</h1>
          <p><code>{run.run_id}</code></p>
        </div>
        <div className="page-header__actions">
          <Link to={`/projects/${encodeURIComponent(projectId)}/phases/${run.phase}`} className="button button--quiet">Back to {run.phase}</Link>
          {cancelAction ? (
            <div className="action-with-reason">
              <button
                type="button"
                className="button button--danger"
                disabled={!cancelAction.enabled || cancelMutation.isPending}
                aria-describedby={!cancelAction.enabled ? cancelReasonId : undefined}
                onClick={() => setConfirmCancel(true)}
              >
                Request cancellation
              </button>
              {!cancelAction.enabled ? (
                <p id={cancelReasonId} className="disabled-reason" role="status">
                  {cancelAction.researcher_message ?? "Cancellation is not available in the current run state."}
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      </header>

      <Panel title="Run progress" eyebrow="Live execution state">
        <RunTimeline run={run} />
      </Panel>

      {stale ? (
        <div className="run-monitor-note" role="status">
          <StatusPill tone="warning">No recent progress signal</StatusPill>
          <p>
            The run has exceeded its recorded activity interval. Review the progress events below. If cancellation is available,
            you may request it; the system does not assume that silence means the scientific work failed.
          </p>
        </div>
      ) : null}

      {correctionNotice ? (
        <div className={correctionNotice.className} role={correctionNotice.role}>
          <div>
            <strong>{correctionNotice.title}</strong>
            <p>{correctionNotice.body}</p>
          </div>
        </div>
      ) : null}

      {recovery === "needs_output_correction" && projection ? (
        <div className="message message--warning" role="status">
          <div>
            <strong>Hermes completed the assigned work.</strong>
            <p>
              Formal publication was withheld because {correctionCount} output{" "}
              {correctionCount === 1 ? "check" : "checks"} require correction. Your current project
              record was not changed.
            </p>
            <p className="run-monitor-note">
              Run-local outputs from the completed work are preserved on disk and remain available
              for inspection.
            </p>
          </div>
        </div>
      ) : run.terminal_reason ? (
        <div className={terminalPresentation.className} role={terminalPresentation.role}>
          <div>
            <strong>{run.terminal_reason.message}</strong>
            <p><code>{run.terminal_reason.code}</code></p>
            {run.terminal_reason.smallest_correction ? (
              <p><span className="message__label">Smallest correction:</span> {run.terminal_reason.smallest_correction}</p>
            ) : null}
          </div>
        </div>
      ) : null}

      {projection && projection.finding_groups.length > 0 ? (
        <Panel title="Findings by class" eyebrow="Output checks">
          <ul className="finding-groups">
            {projection.finding_groups.map((group) => (
              <li key={group.finding_class} className="finding-group">
                <StatusPill tone={findingClassTone(group.finding_class)}>
                  {sentenceCase(group.finding_class)}
                </StatusPill>
                <span className="finding-group__count">
                  {group.count} {group.count === 1 ? "finding" : "findings"}
                </span>
                {group.sample_codes.length > 0 ? (
                  <code className="finding-group__codes">{group.sample_codes.join(", ")}</code>
                ) : null}
                {group.items && group.items.length > 0 ? (
                  <details className="finding-group__details">
                    <summary>Show the {group.items.length === group.count ? group.count : `${group.items.length} of ${group.count}`} finding{group.count === 1 ? "" : "s"}</summary>
                    <ul className="finding-group__items">
                      {group.items.map((item, index) => (
                        <li key={`${item.code}-${index}`} className="finding-group__item">
                          <code>{item.code}</code>
                          {item.object_id ? <span className="finding-group__target">{item.object_id}</span> : null}
                          {item.json_pointer ? <span className="finding-group__target">{item.json_pointer}</span> : null}
                          <span className="finding-group__message">{item.message}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <CorrectionControls projectId={projectId} run={run} onCorrectionSettled={handleCorrectionSettled} />

      <div className="run-detail-grid">
        <Panel title="User direction fixed at launch" eyebrow="Research instructions">
          <p className="preserve-lines">{run.instructions}</p>
          <dl className="record-metadata">
            <div><dt>Requested by</dt><dd>{run.requested_by}</dd></div>
            <div><dt>Requested</dt><dd>{formatDate(run.requested_at)}</dd></div>
          </dl>
        </Panel>
        <Panel title="Frozen scientific basis" eyebrow="Inputs fixed at launch">
          <FrozenBasis run={run} />
          {run.method_identity ? (
            <p className="basis-method">
              Method <code>{run.method_identity.stable_id}</code>, version {run.method_identity.version}
            </p>
          ) : null}
          <p className="run-monitor-note">
            Later changes to formal project state are not silently added to this operation. If publication reports a conflict,
            compare these identities with the current phase record before deciding whether to rerun.
          </p>
        </Panel>
      </div>

      <Panel
        title="Recorded progress events"
        eyebrow="Append-only operation history"
        actions={<StatusPill>{eventsQuery.transport}</StatusPill>}
      >
        {eventsQuery.isLoading ? <LoadingState label="Loading run events..." /> : null}
        {eventsQuery.error ? <ErrorState error={eventsQuery.error} title="Progress events are unavailable" /> : null}
        {eventsQuery.data ? <RunEventList events={eventsQuery.data} /> : null}
      </Panel>

      <div className="run-detail-grid">
        <Panel title="Validation" eyebrow="Contract checks">
          {run.validation_report ? (
            <div className="result-callout">
              <StatusPill tone={run.validation_report.status === "passed" ? "positive" : run.validation_report.status === "failed" ? "danger" : "warning"}>
                {run.validation_report.status}
              </StatusPill>
              <p>{run.validation_report.summary}</p>
              {run.validation_report.href ? <a href={run.validation_report.href}>Open validation report</a> : null}
            </div>
          ) : <p className="muted-text">No validation report has been recorded.</p>}
        </Panel>
        <Panel title="Publication" eyebrow="Formal project state">
          {run.publication_receipt ? (
            <div className="result-callout">
              <StatusPill tone="positive">Published</StatusPill>
              <p>Published {formatDate(run.publication_receipt.published_at)}</p>
              {run.publication_receipt.href ? <a href={run.publication_receipt.href}>Open publication receipt</a> : null}
            </div>
          ) : (
            <EmptyState title="No publication receipt">
              <p>
                {guidance
                  ? "This operation did not replace the current formal result."
                  : "Run-local work remains separate from formal project state until validation and publication complete."}
              </p>
            </EmptyState>
          )}
        </Panel>
      </div>

      {guidance ? (
        <Panel title="What to do next" eyebrow="Recovery guidance">
          <p>{run.terminal_reason?.smallest_correction ?? guidance}</p>
          {run.rerun_prefill ? (
            <Link
              to={`/projects/${encodeURIComponent(projectId)}/phases/${run.phase}?rerun=${encodeURIComponent(run.run_id)}#configure-run`}
              className="button"
            >
              Rerun with the same basis
            </Link>
          ) : null}
          <Link to={`/projects/${encodeURIComponent(projectId)}/phases/${run.phase}#configure-run`} className="button button--quiet">
            Return to {run.phase} run controls
          </Link>
        </Panel>
      ) : null}

      {cancelMutation.error ? <ErrorState error={cancelMutation.error} title="Cancellation was not requested" /> : null}
      {confirmCancel && cancelAction ? (
        <ConfirmActionDialog
          open
          action={cancelAction}
          title={`Request cancellation of ${run.phase} run?`}
          confirmLabel="Request cancellation"
          busy={cancelMutation.isPending}
          onCancel={() => setConfirmCancel(false)}
          onConfirm={(reason) => cancelMutation.mutate(reason)}
        />
      ) : null}
    </div>
  );
}
