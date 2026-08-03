import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import type { ActionDescriptor, MethodRow, PhaseId } from "../api/types";
import { api } from "../api/client";
import { shortDigest } from "../utils/format";
import { CompactPhaseStatus, StatusPill } from "./Status";
import { ConfirmActionDialog } from "./ConfirmActionDialog";
import { ErrorState } from "./Feedback";
import { MethodDetailsDisclosure } from "./MethodDetails";

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
              <th scope="col">Lifecycle</th>
              <th scope="col">Theory</th>
              <th scope="col">Evidence</th>
              <th scope="col">Manuscript</th>
              <th scope="col"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {methods.map((method) => {
              const lifecycleAction = method.actions.find((action) =>
                action.action_type === "retire_method" || action.action_type === "reactivate_method",
              );
              const disabledReasonId = `method-lifecycle-reason-${method.identity.stable_id}-${method.identity.version}`;
              return (
                <tr key={`${method.identity.stable_id}-${method.identity.version}`}>
                  <th scope="row">
                    <span className="method-table__name">{method.display_name}</span>
                    <span className="method-table__summary">{method.summary}</span>
                    <code title={method.identity.definition_sha256}>{method.identity.stable_id}, v{method.identity.version}</code>
                    <MethodDetailsDisclosure method={method} />
                  </th>
                  <td><StatusPill>{method.lifecycle_state}</StatusPill></td>
                  {(["P3", "P4", "P5"] as PhaseId[]).map((phase) => (
                    <td key={phase}><CompactPhaseStatus status={method.phase_statuses[phase]} /></td>
                  ))}
                  <td className="method-table__action">
                    {lifecycleAction ? (
                      <div className="action-with-reason">
                        <button
                          type="button"
                          className="button button--small button--quiet"
                          disabled={!lifecycleAction.enabled}
                          aria-describedby={!lifecycleAction.enabled ? disabledReasonId : undefined}
                          onClick={() => setPending({ method, action: lifecycleAction })}
                        >
                          {lifecycleAction.action_type === "retire_method" ? "Retire" : "Reactivate"}
                        </button>
                        {!lifecycleAction.enabled ? (
                          <p id={disabledReasonId} className="disabled-reason" role="status">
                            {lifecycleAction.researcher_message ?? "This lifecycle change is unavailable in the current method state."}
                          </p>
                        ) : null}
                      </div>
                    ) : (
                      <span className="muted-text">No lifecycle action</span>
                    )}
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
