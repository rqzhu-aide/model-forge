import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { RunDetail } from "../api/types";
import {
  invalidateRunCompletionDependents,
  markTerminalRefreshNeeded,
} from "./useTerminalRunRefresh";

const run = (state: RunDetail["state"]): Pick<RunDetail, "run_id" | "state"> => ({
  run_id: "run-1",
  state,
});

describe("terminal run projection refresh", () => {
  it("deduplicates by client, project, run, and terminal state across remounts", () => {
    const queryClient = new QueryClient();

    expect(markTerminalRefreshNeeded(queryClient, "project-1", run("running"))).toBe(false);
    expect(markTerminalRefreshNeeded(queryClient, "project-1", run("published"))).toBe(true);
    expect(markTerminalRefreshNeeded(queryClient, "project-1", run("published"))).toBe(false);
    expect(markTerminalRefreshNeeded(queryClient, "project-1", run("failed"))).toBe(true);
    expect(markTerminalRefreshNeeded(new QueryClient(), "project-1", run("published"))).toBe(true);
  });

  it("invalidates every researcher-facing dependent query once", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

    await invalidateRunCompletionDependents(queryClient, "project-1");

    expect(invalidate).toHaveBeenCalledTimes(7);
    expect(invalidate).toHaveBeenNthCalledWith(1, { queryKey: ["projects"] });
    expect(invalidate).toHaveBeenNthCalledWith(2, { queryKey: ["overview", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(3, { queryKey: ["phase", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(4, { queryKey: ["methods", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(5, { queryKey: ["runs", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(6, { queryKey: ["run-events", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(7, { queryKey: ["profiles"] });
  });
});
