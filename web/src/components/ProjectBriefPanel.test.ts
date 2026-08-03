import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import type { ActionDescriptor, ProjectBriefView } from "../api/types";
import {
  briefSaveDisabledReason,
  createBriefDraftEnvelope,
  draftFromBrief,
  getBriefScientificChanges,
  invalidateProjectBriefDependents,
  preserveBriefDraftOnClose,
  resolveStoredBriefDraft,
} from "./ProjectBriefPanel";

const updateAction: ActionDescriptor = {
  descriptor_id: "update-brief",
  action_type: "update_project_brief",
  enabled: true,
  consequence_summary: "Replace the formal project brief.",
};

function brief(generationId = "generation-2", artifactId = "artifact-2"): ProjectBriefView {
  return {
    project_id: "project-1",
    record_id: "brief-1",
    generation_id: generationId,
    research_question: "Can the estimator remain stable?",
    domains: ["statistics", "machine learning"],
    intended_use: "Methods paper",
    scope: "Semiparametric estimation",
    decision_criteria: ["Identifiability", "Efficiency"],
    constraints: ["Weak overlap"],
    scope_note: "Formal project scope.",
    published_at: "2026-08-02T12:00:00Z",
    artifact: {
      artifact_id: artifactId,
      label: "Project brief",
      information_layer: "primary",
      href: `/artifacts/${artifactId}`,
    },
    actions: [updateAction],
    projection: {},
  };
}

describe("project brief draft integrity", () => {
  it("restores a stored draft only when its formal generation and artifact are current", () => {
    const current = brief();
    const draft = { ...draftFromBrief(current), scope: "Narrower scope", reason: "Refine scope" };
    const envelope = createBriefDraftEnvelope(current, draft, "2026-08-02T13:00:00Z");

    expect(resolveStoredBriefDraft(JSON.stringify(envelope), current)).toEqual({
      kind: "current",
      envelope,
    });
  });

  it("identifies a stale draft and leaves recovery or discard as explicit choices", () => {
    const prior = brief("generation-1", "artifact-1");
    const current = brief();
    const priorDraft = { ...draftFromBrief(prior), scope: "Earlier draft scope", reason: "Earlier edit" };
    const envelope = createBriefDraftEnvelope(prior, priorDraft, "2026-08-01T13:00:00Z");
    const resolution = resolveStoredBriefDraft(JSON.stringify(envelope), current);

    expect(resolution.kind).toBe("stale");
    if (resolution.kind !== "stale") throw new Error("Expected a stale draft.");
    expect(resolution.envelope.draft).toEqual(priorDraft);
    expect(draftFromBrief(current)).not.toEqual(priorDraft);
  });

  it("preserves the browser-only draft when the formal source changes", () => {
    expect(preserveBriefDraftOnClose(true)).toBe(true);
    expect(preserveBriefDraftOnClose(false)).toBe(false);

    const current = brief();
    const reason = briefSaveDisabledReason({
      brief: current,
      draft: { ...draftFromBrief(current), scope: "Locally revised scope", reason: "Refine scope" },
      action: updateAction,
      sourceChanged: true,
      pending: false,
    });
    expect(reason).toContain("restore or discard the browser-only draft");
  });

  it("disables a reason-only save when no scientific field changed", () => {
    const current = brief();
    const draft = { ...draftFromBrief(current), reason: "A reason without a change" };

    expect(getBriefScientificChanges(current, draft)).toEqual({});
    expect(briefSaveDisabledReason({
      brief: current,
      draft,
      action: updateAction,
      sourceChanged: false,
      pending: false,
    })).toBe("Change at least one scientific field before saving.");
  });

  it("preserves intentional clearing of optional scientific fields", () => {
    const current = brief();
    const draft = {
      ...draftFromBrief(current),
      scope: "",
      decisionCriteria: "",
      constraints: "",
      reason: "Remove constraints that no longer apply",
    };

    expect(getBriefScientificChanges(current, draft)).toEqual({
      scope: "",
      decision_criteria: [],
      constraints: [],
    });
  });

  it("constructs a payload fragment containing changed scientific fields only", () => {
    const current = brief();
    const draft = {
      ...draftFromBrief(current),
      intendedUse: "Methods and biological application",
      constraints: "Weak overlap\nLimited sample size",
      reason: "Add the planned application and sample-size constraint",
    };

    expect(getBriefScientificChanges(current, draft)).toEqual({
      intended_use: "Methods and biological application",
      constraints: ["Weak overlap", "Limited sample size"],
    });
  });
});

describe("project brief cache consistency", () => {
  it("refreshes project and all phase projections after an update", async () => {
    const queryClient = new QueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue(undefined);

    await invalidateProjectBriefDependents(queryClient, "project-1");

    expect(invalidate).toHaveBeenCalledTimes(4);
    expect(invalidate).toHaveBeenNthCalledWith(1, { queryKey: ["projects"] });
    expect(invalidate).toHaveBeenNthCalledWith(2, { queryKey: ["overview", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(3, { queryKey: ["phase", "project-1"] });
    expect(invalidate).toHaveBeenNthCalledWith(4, { queryKey: ["methods", "project-1"] });
  });
});
