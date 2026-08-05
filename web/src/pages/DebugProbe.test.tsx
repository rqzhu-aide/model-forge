// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { PhaseView, ReviewedBasis, ReviewedRoleResource } from "../api/types";
import { PhasePage } from "./PhasePage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getPhaseView: vi.fn(),
      listMethods: vi.fn(),
    },
  };
});

function roleResource(overrides: Partial<ReviewedRoleResource> = {}): ReviewedRoleResource {
  return {
    profile: "research_lead",
    profile_version: "2026-07-01",
    soul_sha256: "b".repeat(64),
    skills: [],
    model: null,
    provider: null,
    memory_policy: "persistent",
    phase_instruction: null,
    tools: null,
    ...overrides,
  };
}

function reviewedBasis(overrides: Partial<ReviewedBasis> = {}): ReviewedBasis {
  return {
    authority_head: {
      authority_sequence: 7,
      authority_root_sha256: "a".repeat(64),
      current_revision: 3,
    },
    reviewed_current_inputs: [
      { option_id: "p1.sources", generation_id: "gen-1", sha256: "e".repeat(64) },
      { option_id: "p1.synthesis", generation_id: "gen-2", sha256: "f".repeat(64) },
    ],
    method_identity: { stable_id: "m_synthesis", version: 2, definition_sha256: "d".repeat(64) },
    role_resources: {
      research_lead: roleResource({
        skills: [
          {
            skill_id: "literature_review",
            source: "library",
            source_revision: "r1",
            bundle_sha256: "c".repeat(64),
          },
        ],
        model: "gpt-4o",
        provider: "openai",
        phase_instruction: "Synthesize the literature basis.",
        tools: "web_search",
      }),
    },
    ...overrides,
  };
}

function phaseView(overrides: Partial<PhaseView> = {}): PhaseView {
  return {
    phase_id: "P1",
    name: "Literature basis",
    purpose: "Establish the current literature basis.",
    assessment: {
      record_position: "none",
      alignment: "unassessed",
      attention: "none",
      scientific_outcome: "not_assessed",
    },
    evidence: [],
    artifacts: [],
    run_configuration: {
      modes: [
        {
          mode_id: "p1.standard",
          label: "Standard",
          description: "Single-pass synthesis of the current literature basis.",
        },
      ],
      default_mode: "p1.standard",
      instruction_label: "Instructions",
      instruction_help: "State the synthesis instructions.",
      current_inputs: [],
      history_options: [],
      stage_plan: [{ stage_id: "s1", label: "Synthesize", roles: ["research_lead"], execution: "serial" }],
    },
    actions: [],
    active_runs: [],
    recent_runs: [],
    descriptor_basis: reviewedBasis(),
    projection: {},
    ...overrides,
  };
}

let queryClient: QueryClient;

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/projects/project-1/phases/P1"]}>
        <Routes>
          <Route path="/projects/:projectId/phases/:phaseId" element={<PhasePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

afterEach(() => {
  cleanup();
});

describe("debug", () => {
  it("probes the real fixture", async () => {
    vi.mocked(api.getPhaseView).mockResolvedValue(phaseView());

    renderPage();

    await waitFor(() => {
      expect(vi.mocked(api.getPhaseView).mock.calls.length).toBeGreaterThan(0);
    });
    await screen.findByText("Literature basis", {}, { timeout: 3000 });
    console.log("FOUND TITLE");
    console.log("calls:", vi.mocked(api.getPhaseView).mock.calls.length);
  });
});
