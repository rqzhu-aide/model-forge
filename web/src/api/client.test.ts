import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./client";
import type { ActionDescriptor } from "./types";

const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("command idempotency", () => {
  it("adds one fresh idempotency key to every mutation and none to reads", async () => {
    const calls: Array<{ path: string; init: RequestInit | undefined }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push({ path, init });
      if (path.endsWith("/lifecycle")) return new Response(null, { status: 204 });
      return new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const lifecycleAction: ActionDescriptor = {
      descriptor_id: "retire-method",
      action_type: "retire_method",
      enabled: true,
      consequence_summary: "Retire the method.",
    };
    const cancelAction: ActionDescriptor = {
      descriptor_id: "cancel-run",
      action_type: "cancel_run",
      enabled: true,
      consequence_summary: "Request cancellation.",
    };

    await api.createProject({
      name: "Test",
      research_question: "Does the method work?",
      domains: ["statistics"],
      intended_use: "Methods study",
    });
    await api.changeMethodLifecycle("project", "method", lifecycleAction, "No longer pursued");
    await api.startRun("project", {
      action_descriptor_id: "start-run",
      phase: "P3",
      mode: "p3.develop",
      choice_values: {},
      context_policy: "current_only",
      selected_context_option_ids: [],
    });
    await api.cancelRun("project", "run", cancelAction, "Researcher requested stop");
    await api.saveProfile("project", "lead", "lead-profile", "save-profile");
    await api.installSkill("project", "lead", "writing", "install-writing");
    await api.updateProjectBrief("project", {
      action_descriptor_id: "update-brief",
      reason: "Refine the scientific scope",
      scope: "Semiparametric estimation under weak overlap.",
    });
    await api.listProjects();
    await api.getSystemSettings();

    const mutationCalls = calls.slice(0, 7);
    const keys = mutationCalls.map(({ init }) => new Headers(init?.headers).get("Idempotency-Key"));
    expect(keys).toHaveLength(7);
    keys.forEach((key) => expect(key).toMatch(uuidPattern));
    expect(new Set(keys).size).toBe(keys.length);
    expect(new Headers(calls[7]?.init?.headers).has("Idempotency-Key")).toBe(false);
    expect(new Headers(calls[8]?.init?.headers).has("Idempotency-Key")).toBe(false);
  });
});
