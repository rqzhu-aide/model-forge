// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type {
  PhaseView,
  ReviewedBasis,
  ReviewedRoleResource,
} from "../api/types";
import { shortDigest } from "../utils/format";
import { PhasePage } from "./PhasePage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getPhaseView: vi.fn(),
      getRun: vi.fn(),
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
          <Route
            path="/projects/:projectId/phases/:phaseId"
            element={<PhasePage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// The page re-fetches once the default run mode is resolved (the query key
// includes the mode), so wait until both the phase and the run-scope loading
// states are gone before asserting on the settled tree.
async function settle() {
  await waitFor(() => {
    expect(screen.queryByText("Loading P1 state…")).not.toBeInTheDocument();
    expect(screen.queryByText("Resolving the default run scope…")).not.toBeInTheDocument();
  });
}

beforeEach(() => {
  vi.resetAllMocks();
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

afterEach(() => {
  cleanup();
});

describe("PhasePage reviewed basis", () => {
  it("renders every reviewed-basis section with its sealed values", async () => {
    vi.mocked(api.getPhaseView).mockResolvedValue(phaseView());

    renderPage();
    await settle();

    expect(screen.getByText("What a run command seals")).toBeInTheDocument();
    expect(screen.getByText(/Review the sealed basis · 2 current inputs · 1 role/)).toBeInTheDocument();

    // Authority head.
    expect(screen.getByText("Authority head")).toBeInTheDocument();
    expect(screen.getByText("Authority sequence")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.getByText("Current revision")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();

    // Reviewed current inputs.
    expect(screen.getByText("Reviewed current inputs")).toBeInTheDocument();
    expect(screen.getByText("p1.sources")).toBeInTheDocument();
    expect(screen.getByText("gen-1")).toBeInTheDocument();
    expect(screen.getByText("p1.synthesis")).toBeInTheDocument();
    expect(screen.getByText("gen-2")).toBeInTheDocument();

    // Method binding.
    expect(screen.getByText("Method binding")).toBeInTheDocument();
    expect(screen.getByText("m_synthesis")).toBeInTheDocument();

    // Role resources.
    expect(screen.getByText("Role resources")).toBeInTheDocument();
    expect(screen.getByText("research_lead, v2026-07-01")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
    expect(screen.getByText("openai")).toBeInTheDocument();
    expect(screen.getByText("Synthesize the literature basis.")).toBeInTheDocument();
    expect(screen.getByText("web_search")).toBeInTheDocument();

    // Sealed skills.
    expect(screen.getByText("literature_review")).toBeInTheDocument();
    expect(screen.getByText("library@r1")).toBeInTheDocument();
  });

  it("truncates sealed digests and keeps the full digest in the title", async () => {
    vi.mocked(api.getPhaseView).mockResolvedValue(phaseView());

    renderPage();
    await settle();

    expect(screen.getByTitle("a".repeat(64))).toHaveTextContent(shortDigest("a".repeat(64)));
    expect(screen.getByTitle("b".repeat(64))).toHaveTextContent(shortDigest("b".repeat(64)));
    expect(screen.getByTitle("c".repeat(64))).toHaveTextContent(shortDigest("c".repeat(64)));
    expect(screen.getByTitle("d".repeat(64))).toHaveTextContent(shortDigest("d".repeat(64)));
    expect(screen.getByTitle("e".repeat(64))).toHaveTextContent(shortDigest("e".repeat(64)));
    expect(screen.getByTitle("f".repeat(64))).toHaveTextContent(shortDigest("f".repeat(64)));
  });

  it("renders explicit labels when the basis seals nulls", async () => {
    vi.mocked(api.getPhaseView).mockResolvedValue(
      phaseView({
        descriptor_basis: reviewedBasis({
          method_identity: null,
          reviewed_current_inputs: [],
          role_resources: {
            research_lead: roleResource({ memory_policy: "read_only" }),
          },
        }),
      }),
    );

    renderPage();
    await settle();

    expect(screen.getByText("Not method-bound.")).toBeInTheDocument();
    expect(screen.getByText("No current inputs were reviewed for this command.")).toBeInTheDocument();
    expect(screen.getAllByText("Not configured")).toHaveLength(3); // model, provider, tools
    expect(screen.getByText("None in contract")).toBeInTheDocument(); // phase instruction
  });

  it("shows an explicit note when the view has no sealed basis", async () => {
    vi.mocked(api.getPhaseView).mockResolvedValue(
      phaseView({ descriptor_basis: null }),
    );

    renderPage();
    await settle();

    expect(screen.getByText("Sealed basis for this view")).toBeInTheDocument();
    expect(screen.getByText("No sealed basis for this view.")).toBeInTheDocument();
    expect(screen.queryByText("Authority head")).not.toBeInTheDocument();
  });

  it("explains each memory policy in plain language", async () => {
    vi.mocked(api.getPhaseView).mockResolvedValue(
      phaseView({
        descriptor_basis: reviewedBasis({
          role_resources: {
            persistent_role: roleResource({ memory_policy: "persistent" }),
            ephemeral_role: roleResource({ memory_policy: "ephemeral" }),
            read_only_role: roleResource({ memory_policy: "read_only" }),
          },
        }),
      }),
    );

    renderPage();
    await settle();

    expect(screen.getByText(/keeps project memory between runs/)).toBeInTheDocument();
    expect(screen.getByText(/fresh every run/)).toBeInTheDocument();
    expect(screen.getByText(/reads memory, never writes/)).toBeInTheDocument();
  });
});

describe("PhasePage one-click rerun (WP-UX)", () => {
  function rerunView(): PhaseView {
    return phaseView({
      run_configuration: {
        modes: [
          {
            mode_id: "p1.standard",
            label: "Standard",
            description: "Single-pass synthesis.",
          },
          {
            mode_id: "p1.deep",
            label: "Deep sweep",
            description: "Two-pass deep synthesis.",
          },
        ],
        default_mode: "p1.standard",
        instruction_label: "Instructions",
        instruction_help: "State the synthesis instructions.",
        current_inputs: [],
        history_options: [],
        stage_plan: [
          { stage_id: "s1", label: "Synthesize", roles: ["research_lead"], execution: "serial" },
        ],
      },
    });
  }

  function sourceRun() {
    return {
      run_id: "run.p1.p1-deep.abc123",
      phase: "P1",
      mode: "p1.deep",
      state: "failed",
      requested_by: "researcher.demo",
      requested_at: "2026-08-28T10:00:00Z",
      updated_at: "2026-08-28T10:30:00Z",
      actions: [],
      rerun_prefill: {
        phase: "P1",
        mode: "p1.deep",
        choice_values: { "p1.instructions": "Repeat the deep sweep exactly." },
        context_policy: "current_only",
      },
    };
  }

  it("applies the frozen mode even when the phase view resolves first (B1)", async () => {
    // The phase view wins the race; the default-mode effect must still wait
    // for the rerun prefill instead of locking in the default mode.
    (api.getPhaseView as ReturnType<typeof vi.fn>).mockResolvedValue(rerunView());
    (api.getRun as ReturnType<typeof vi.fn>).mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve(sourceRun()), 20)),
    );
    (api.listMethods as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/projects/project-1/phases/P1?rerun=run.p1.p1-deep.abc123"]}>
          <Routes>
            <Route path="/projects/:projectId/phases/:phaseId" element={<PhasePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(screen.getByRole("radio", { name: /Deep sweep/i })).toBeChecked();
    });
    expect(screen.getByRole("radio", { name: /Standard/i })).not.toBeChecked();
    await waitFor(() => {
      expect(screen.getByRole("textbox", { name: /instructions/i })).toHaveValue(
        "Repeat the deep sweep exactly.",
      );
    });
    expect(screen.getByText(/Review every choice before launch/i)).toBeInTheDocument();
  });

  it("shows a note when the source run offers no rerun basis (B3)", async () => {
    (api.getPhaseView as ReturnType<typeof vi.fn>).mockResolvedValue(rerunView());
    (api.getRun as ReturnType<typeof vi.fn>).mockResolvedValue({
      ...sourceRun(),
      rerun_prefill: undefined,
    });
    (api.listMethods as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={["/projects/project-1/phases/P1?rerun=run.p1.p1-deep.abc123"]}>
          <Routes>
            <Route path="/projects/:projectId/phases/:phaseId" element={<PhasePage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/does not offer a rerun basis/i),
      ).toBeInTheDocument();
    });
  });
});

