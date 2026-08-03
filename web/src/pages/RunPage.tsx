import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { RunDetail, RunLifecycleState } from "../api/types";
import { ConfirmActionDialog } from "../components/ConfirmActionDialog";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { FrozenBasis, RunEventList, RunTimeline, runIsStale } from "../components/RunTimeline";
import { StatusPill } from "../components/Status";
import { useRunEvents } from "../hooks/useRunEvents";
import { useTerminalRunRefresh } from "../hooks/useTerminalRunRefresh";
import { formatDate, isRunActive } from "../utils/format";
import { NotFoundPage } from "./NotFoundPage";

function recoveryGuidance(run: RunDetail): string | undefined {
  if (run.state === "failed") {
    return "Inspect the terminal reason and progress events, then return to the phase to configure a corrected rerun. The failed attempt did not replace formal project state.";
  }
  if (run.state === "rejected") {
    return "Review the validation report and correct the stated contract or scientific output before starting a new run. Rejected output was not published.";
  }
  if (run.state === "conflicted") {
    return "Compare this run's frozen basis with the current phase record. If the current basis should be used, return to the phase and start a new run with that context.";
  }
  if (run.state === "cancelled") {
    return "The run stopped without changing the current formal result. Return to the phase when you want to revise the instructions or start another run.";
  }
  return undefined;
}

export function terminalReasonPresentation(state: RunLifecycleState): {
  className: string;
  role: "alert" | "status";
} {
  if (state === "failed" || state === "rejected") {
    return { className: "message message--error", role: "alert" };
  }
  if (state === "conflicted") {
    return { className: "message message--warning", role: "status" };
  }
  return { className: "message message--neutral", role: "status" };
}

export async function invalidateCancellationRequestDependents(
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
      return run && isRunActive(run.state) ? 4_000 : false;
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
  const recovery = recoveryGuidance(run);
  const stale = runIsStale(run);
  const cancelReasonId = `cancel-run-disabled-${run.run_id}`;
  const terminalPresentation = terminalReasonPresentation(run.state);

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

      {run.terminal_reason ? (
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
                {recovery
                  ? "This operation did not replace the current formal result."
                  : "Run-local work remains separate from formal project state until validation and publication complete."}
              </p>
            </EmptyState>
          )}
        </Panel>
      </div>

      {recovery ? (
        <Panel title="What to do next" eyebrow="Recovery guidance">
          <p>{run.terminal_reason?.smallest_correction ?? recovery}</p>
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
