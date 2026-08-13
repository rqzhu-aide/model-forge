import { useEffect } from "react";
import type { QueryClient } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import type { RunDetail, RunLifecycleState } from "../api/types";

const TERMINAL_RUN_STATES: ReadonlySet<RunLifecycleState> = new Set([
  "published",
  "failed",
  "rejected",
  "conflicted",
  "cancelled",
  "correction_exhausted",
]);

export function isTerminalRunState(state: RunLifecycleState): boolean {
  return TERMINAL_RUN_STATES.has(state);
}

const terminalRefreshesByClient = new WeakMap<QueryClient, Set<string>>();

function terminalRefreshRegistry(queryClient: QueryClient): Set<string> {
  const existing = terminalRefreshesByClient.get(queryClient);
  if (existing) return existing;
  const created = new Set<string>();
  terminalRefreshesByClient.set(queryClient, created);
  return created;
}

export function markTerminalRefreshNeeded(
  queryClient: QueryClient,
  projectId: string,
  run: Pick<RunDetail, "run_id" | "state"> | undefined,
): boolean {
  if (!projectId || !run || !isTerminalRunState(run.state)) return false;
  const key = `${projectId}:${run.run_id}:${run.state}`;
  const refreshedRuns = terminalRefreshRegistry(queryClient);
  if (refreshedRuns.has(key)) return false;
  refreshedRuns.add(key);
  return true;
}

export async function invalidateRunCompletionDependents(
  queryClient: QueryClient,
  projectId: string,
): Promise<void> {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["projects"] }),
    queryClient.invalidateQueries({ queryKey: ["overview", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["phase", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["methods", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["run-events", projectId] }),
    queryClient.invalidateQueries({ queryKey: ["profiles"] }),
  ]);
}

/**
 * Refresh researcher-facing projections once after the canonical run query first
 * reports a terminal state. Both SSE and polling update that same query, so this
 * effect has one completion path and cannot create an invalidation loop.
 */
export function useTerminalRunRefresh(projectId: string, run: RunDetail | undefined): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!markTerminalRefreshNeeded(queryClient, projectId, run)) return;
    void invalidateRunCompletionDependents(queryClient, projectId);
  }, [projectId, queryClient, run]);
}
