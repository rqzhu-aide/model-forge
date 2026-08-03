import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { ActionDescriptor, ContextOption, MethodRow } from "../api/types";
import {
  actionForSelection,
  invalidateRunStartDependents,
  methodIdentitiesMatch,
  selectedContextReviewItems,
} from "./RunForm";

const options: ContextOption[] = [
  {
    option_id: "current-method",
    label: "Current method definition",
    description: "Exact Phase 2 method record.",
    artifact_pointer: {
      artifact_id: "artifact-method",
      uri: "artifact://method",
      sha256: "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
    },
    selected_by_default: true,
    required: true,
  },
  {
    option_id: "prior-proof",
    label: "Earlier proof attempt",
    description: "Optional historical proof.",
    artifact_pointer: {
      artifact_id: "artifact-proof",
      uri: "artifact://proof",
      sha256: "abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd",
    },
    selected_by_default: false,
    required: false,
  },
  {
    option_id: "registered-context-without-digest",
    label: "Registered context without an exposed digest",
    description: "A typed context option whose pointer is not exposed here.",
    selected_by_default: false,
    required: false,
  },
];

describe("final run context review", () => {
  it("lists only selected inputs with human labels and short digests", () => {
    expect(selectedContextReviewItems(options, new Set(["current-method"]))).toEqual([
      {
        optionId: "current-method",
        label: "Current method definition",
        digest: "12345678…abcdef",
      },
    ]);
  });

  it("retains the exact option ID when no artifact digest is exposed", () => {
    expect(selectedContextReviewItems(
      options,
      new Set(["registered-context-without-digest"]),
    )).toEqual([
      {
        optionId: "registered-context-without-digest",
        label: "Registered context without an exposed digest",
        digest: "registered-context-without-digest",
      },
    ]);
  });
});

describe("exact method action identity", () => {
  const identity = {
    stable_id: "method-1",
    version: 3,
    definition_sha256: "definition-current",
  };

  it("accepts only the full selected method identity", () => {
    expect(methodIdentitiesMatch(identity, { ...identity })).toBe(true);
    expect(methodIdentitiesMatch(identity, { ...identity, version: 2 })).toBe(false);
    expect(methodIdentitiesMatch(identity, {
      ...identity,
      definition_sha256: "definition-earlier",
    })).toBe(false);
  });
});

describe("run start cache consistency", () => {
  it("refreshes projects, all phases, runs, overview, methods, and profile locks", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

    await invalidateRunStartDependents(queryClient, "project-1");

    expect(invalidate).toHaveBeenCalledTimes(6);
    expect(invalidate).toHaveBeenNthCalledWith(1, { queryKey: ["projects"] });
    expect(invalidate).toHaveBeenNthCalledWith(2, { queryKey: ["phase", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(3, { queryKey: ["runs", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(4, { queryKey: ["overview", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(5, { queryKey: ["methods", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(6, { queryKey: ["profiles"] });
  });
});

describe("method-bound start action selection", () => {
  const method = {
    identity: {
      stable_id: "method-1",
      version: 3,
      definition_sha256: "definition-current",
    },
  } as MethodRow;
  const baseAction: ActionDescriptor = {
    descriptor_id: "start-p3",
    action_type: "start_run",
    enabled: true,
    consequence_summary: "Start the theory run.",
    command_contract: {
      phase: "P3",
      phase_contract_version: "1",
      phase_contract_sha256: "contract",
      mode: "p3.theory",
    },
  };

  it("fails closed when a selected method is not bound by exact identity", () => {
    expect(actionForSelection([baseAction], "p3.theory", method)).toBeUndefined();
    expect(actionForSelection([{
      ...baseAction,
      method_identity: { ...method.identity, version: 2 },
    }], "p3.theory", method)).toBeUndefined();
    expect(actionForSelection([{
      ...baseAction,
      method_identity: {
        ...method.identity,
        definition_sha256: "definition-earlier",
      },
    }], "p3.theory", method)).toBeUndefined();
  });

  it("accepts an exact method-bound descriptor", () => {
    const exact = { ...baseAction, method_identity: method.identity };
    expect(actionForSelection([exact], "p3.theory", method)).toBe(exact);
  });
});
