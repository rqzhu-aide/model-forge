import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { ProjectSummary } from "../api/types";
import {
  changedProjectSummaryIds,
  invalidateProjectSummaryDependents,
  projectSummaryPollInterval,
} from "./AppShell";

function project(
  projectId: string,
  activeRunCount: number,
  updatedAt: string,
): ProjectSummary {
  return {
    project_id: projectId,
    name: projectId,
    research_question: "Research question",
    domains: ["statistics"],
    updated_at: updatedAt,
    active_run_count: activeRunCount,
  };
}

describe("persistent project summary monitoring", () => {
  it("polls only while at least one project has an active run", () => {
    expect(projectSummaryPollInterval(undefined)).toBe(false);
    expect(projectSummaryPollInterval([project("project-1", 0, "t1")])).toBe(false);
    expect(projectSummaryPollInterval([
      project("project-1", 0, "t1"),
      project("project-2", 1, "t1"),
    ])).toBe(4_000);
  });

  it("detects only active-run-count or update-time transitions", () => {
    const previous = [
      project("project-1", 1, "t1"),
      project("project-2", 0, "t1"),
      project("project-3", 0, "t1"),
    ];
    const current = [
      project("project-1", 0, "t1"),
      project("project-2", 0, "t2"),
      project("project-3", 0, "t1"),
    ];

    expect(changedProjectSummaryIds(undefined, current)).toEqual([]);
    expect(changedProjectSummaryIds(previous, current)).toEqual([
      "project-1",
      "project-2",
    ]);
  });

  it("refreshes each affected project and global profiles without touching projects", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

    await invalidateProjectSummaryDependents(
      queryClient,
      ["project-1", "project-1", "project-2"],
    );

    expect(invalidate).toHaveBeenCalledTimes(13);
    expect(invalidate).toHaveBeenNthCalledWith(1, { queryKey: ["overview", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(2, { queryKey: ["phase", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(3, { queryKey: ["methods", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(4, { queryKey: ["runs", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(5, { queryKey: ["run", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(6, { queryKey: ["run-events", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(7, { queryKey: ["overview", "project-2"] });
    expect(invalidate).toHaveBeenNthCalledWith(8, { queryKey: ["phase", "project-2"] });
    expect(invalidate).toHaveBeenNthCalledWith(9, { queryKey: ["methods", "project-2"] });
    expect(invalidate).toHaveBeenNthCalledWith(10, { queryKey: ["runs", "project-2"] });
    expect(invalidate).toHaveBeenNthCalledWith(11, { queryKey: ["run", "project-2"] });
    expect(invalidate).toHaveBeenNthCalledWith(12, { queryKey: ["run-events", "project-2"] });
    expect(invalidate).toHaveBeenNthCalledWith(13, { queryKey: ["profiles"] });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["projects"] });
  });
});
