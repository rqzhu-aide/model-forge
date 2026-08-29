import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { MethodRow } from "../api/types";
import {
  invalidateMethodLifecycleDependents,
  methodLifecycleConfirmationTitle,
} from "./MethodTable";

const method = {
  display_name: "Stabilized one-step estimator",
  identity: {
    stable_id: "method-stable-id",
    version: 4,
    definition_sha256: "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
  },
} as MethodRow;

describe("method lifecycle confirmation identity", () => {
  it("names the exact method version and definition digest before retirement", () => {
    expect(methodLifecycleConfirmationTitle("retire_method", method)).toBe(
      "Retire Stabilized one-step estimator, v4 (definition 12345678…abcdef)?",
    );
  });

  it("uses the same exact identity before reactivation", () => {
    expect(methodLifecycleConfirmationTitle("reactivate_method", method)).toBe(
      "Reactivate Stabilized one-step estimator, v4 (definition 12345678…abcdef)?",
    );
  });

  it("names activation for a proposed method (D-3)", () => {
    expect(methodLifecycleConfirmationTitle("activate_method", method)).toBe(
      "Activate Stabilized one-step estimator, v4 (definition 12345678…abcdef)?",
    );
  });
});

describe("method lifecycle cache consistency", () => {
  it("refreshes the method catalog, every phase view, and the overview", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

    await invalidateMethodLifecycleDependents(queryClient, "project-1");

    expect(invalidate).toHaveBeenCalledTimes(3);
    expect(invalidate).toHaveBeenNthCalledWith(1, { queryKey: ["methods", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(2, { queryKey: ["phase", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(3, { queryKey: ["overview", "project-1"] });
  });
});
