import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import type { ActionDescriptor, MethodRow, PhaseId } from "../api/types";
import { api } from "../api/client";
import { shortDigest, phaseShortNames } from "../utils/format";
import { CompactPhaseStatus, StatusPill } from "./Status";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { ErrorState } from "./Feedback";
import { MathText } from "./MathText";
import { MethodDetailsDisclosure } from "./MethodDetails";
import { MethodScores } from "./MethodScores";

interface PendingLifecycleAction {
  method: MethodRow;
  action: ActionDescriptor;
}

export function methodLifecycleConfirmationTitle(
  actionType: "retire_method" | "reactivate_method",
  method: MethodRow,
): string {
  const verb = actionType === "retire_method" ? "Retire" : "Reactivate";
  return `${verb} ${method.display_name}, v${method.identity.version} (definition ${shortDigest(method.identity.definition_sha256)})?`;
}

export async function invalidateMethodLifecycleDependents(
  queryClient: QueryClient,
  projectId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["methods", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["phase", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["overview", projectId] }),
  ]);
}

/**
 * Row description (Tez direction, 2026-08-21): the plain summary clamped to
 * two lines at full cell width; the Novel/Risk/Assumes category lines were
 * retired as not on point for scanning - that content lives in the details
 * disclosure.
 */
export function shortMethodName(displayName: string): string {
  return displayName.split(/\s+—\s+/)[0] ?? displayName;
}

export function MethodTable({ projectId, methods }: { projectId: string; methods: MethodRow[] }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<PendingLifecycleAction>();
  const mutation = useMutation({
    mutationFn: ({ method, action, reason }: PendingLifecycleAction & { reason: string }) =>
      api.changeMethodLifecycle(projectId, method.identity.stable_id, action, reason),
    onSuccess: async () => {
      setPending(undefined);
      await invalidateMethodLifecycleDependents(queryClient, projectId);
    },
  });

  return (
    <>
      <div className="table-scroll" role="region" aria-label="Current method catalog" tabIndex={0}>
        <table className="method-table">
          <caption className="sr-only">Current methods, exact versions, scientific phase state, and lifecycle actions</caption>
          <thead>
            <tr>
              <th scope="col">Method</th>
              <th scope="col">Phase status and lead evaluation</th>
            </tr>
          </thead>
          <tbody>
            {methods.map((method) => {
              const lifecycleAction = method.actions.find((action) =>
                action.action_type === "retire_method" || action.action_type === "reactivate_method",
              );
              const actionLabel = lifecycleAction?.action_type === "retire_method" ? "Retire" : "Reactivate";
              const disabledReason = lifecycleAction && !lifecycleAction.enabled
                ? (lifecycleAction.researcher_message ?? "This lifecycle change is unavailable in the current method state.")
                : undefined;
              return (
                <tr key={`${method.identity.stable_id}-${method.identity.version}`}>
                  <th scope="row">
                    <span className="method-table__title-row">
                      <span
                        className="method-table__name"
                        title={shortMethodName(method.display_name) !== method.display_name ? method.display_name : undefined}
                      >
                        <MathText text={shortMethodName(method.display_name)} />
                      </span>
                      <StatusPill>{method.lifecycle_state}</StatusPill>
                      {lifecycleAction ? (
                        <button
                          type="button"
                          className={`button button--small ${lifecycleAction.action_type === "retire_method" ? "button--danger" : "button--quiet"}`}
                          disabled={!lifecycleAction.enabled}
                          title={disabledReason}
                          aria-label={disabledReason ? `${actionLabel} (unavailable: ${disabledReason})` : undefined}
                          onClick={() => setPending({ method, action: lifecycleAction })}
                        >
                          {actionLabel}
                        </button>
                      ) : null}
                    </span>
                    <span className="method-table__summary method-table__summary--clamped"><MathText text={method.summary} /></span>
                    <code title={method.identity.definition_sha256}>{method.identity.stable_id}, v{method.identity.version}</code>
                    <MethodDetailsDisclosure method={method} />
                  </th>
                  <td className="method-table__panel">
                    <span className="method-table__panel-row">
                      {(["P3", "P4", "P5"] as PhaseId[]).map((phase) => (
                        <span className="method-table__panel-item" key={phase}>
                          <span className="method-table__panel-label">{phaseShortNames[phase]}</span>
                          <CompactPhaseStatus status={method.phase_statuses[phase]} />
                          {phase === "P3" && method.lifecycle_state === "active" ? (
                            <Link
                              className="button button--small button--quiet method-table__run-p3"
                              to={`/projects/${encodeURIComponent(projectId)}/phases/P3?method=${encodeURIComponent(method.identity.stable_id)}`}
                              title={`Configure a Phase 3 theory run for ${shortMethodName(method.display_name)}`}
                            >
                              Run P3 →
                            </Link>
                          ) : null}
                        </span>
                      ))}
                    </span>
                    <span className="method-table__panel-row method-table__panel-row--scores">
                      <MethodScores evaluation={method.evaluation} />
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {mutation.error ? <ErrorState error={mutation.error} title="Method state was not changed" /> : null}
      {pending ? (
        <ConfirmActionDialog
          open
          action={pending.action}
          title={methodLifecycleConfirmationTitle(
            pending.action.action_type === "retire_method" ? "retire_method" : "reactivate_method",
            pending.method,
          )}
          confirmLabel={pending.action.action_type === "retire_method" ? "Retire method" : "Reactivate method"}
          busy={mutation.isPending}
          onCancel={() => setPending(undefined)}
          onConfirm={(reason) => mutation.mutate({ ...pending, reason })}
        />
      ) : null}
    </>
  );
}
