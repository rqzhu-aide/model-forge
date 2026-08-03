import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import {
  invalidateCancellationRequestDependents,
  terminalReasonPresentation,
} from "./RunPage";

describe("terminal run reason presentation", () => {
  it("separates errors, conflicts, and neutral cancellation", () => {
    expect(terminalReasonPresentation("failed")).toEqual({
      className: "message message--error",
      role: "alert",
    });
    expect(terminalReasonPresentation("rejected").role).toBe("alert");
    expect(terminalReasonPresentation("conflicted")).toEqual({
      className: "message message--warning",
      role: "status",
    });
    expect(terminalReasonPresentation("cancelled")).toEqual({
      className: "message message--neutral",
      role: "status",
    });
  });
});

describe("cancellation request cache consistency", () => {
  it("refreshes run state and profile locks after a request", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

    await invalidateCancellationRequestDependents(queryClient, "project-1", "P4");

    expect(invalidate).toHaveBeenCalledTimes(4);
    expect(invalidate).toHaveBeenNthCalledWith(1, { queryKey: ["runs", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(2, { queryKey: ["phase", "project-1", "P4"] });
    expect(invalidate).toHaveBeenNthCalledWith(3, { queryKey: ["overview", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(4, { queryKey: ["profiles"] });
  });
});
