// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { ProjectOverview } from "../api/types";
import { ProjectOverviewPage } from "./ProjectOverviewPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getProjectOverview: vi.fn(),
      listMethods: vi.fn(),
      listRuns: vi.fn(),
      getPhaseView: vi.fn(),
      listMaterials: vi.fn(),
    },
  };
});

function overview(overrides: Partial<ProjectOverview> = {}): ProjectOverview {
  return {
    project: {
      project_id: "project-1",
      name: "Test project",
      research_question: "Does the overview render error states?",
      domains: [],
      active_run_count: 0,
    },
    project_brief: {
      project_id: "project-1",
      record_id: "rec-1",
      generation_id: "gen-1",
      research_question: "Does the overview render error states?",
      domains: [],
      intended_use: "Testing.",
      scope: "Unit tests.",
      decision_criteria: [],
      constraints: [],
      scope_note: "",
      published_at: "2026-09-01T00:00:00Z",
      artifact: {
        artifact_id: "art-1",
        label: "Project brief",
        information_layer: "primary",
        href: "/artifacts/art-1",
      },
      actions: [],
      projection: {},
    },
    methods: [],
    phases: ["P1", "P2", "P3", "P4", "P5"].map((phase) => ({
      phase_id: phase as ProjectOverview["phases"][number]["phase_id"],
      name: phase,
      navigation_state: "current_records" as const,
      formal_record_count: 1,
      method_scoped_record_count: 0,
      active_run_count: 0,
      assessment: {},
      summary: "",
    })),
    active_runs: [],
    attention_items: [],
    storage: {
      storage_kind: "backend_managed",
      open_folder_supported: false,
      explanation: "Managed by the backend.",
    },
    actions: [],
    projection: {},
    ...overrides,
  };
}

let queryClient: QueryClient;

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/projects/project-1"]}>
        <Routes>
          <Route path="/projects/:projectId" element={<ProjectOverviewPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.resetAllMocks();
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(api.getProjectOverview).mockResolvedValue(overview());
  vi.mocked(api.listMethods).mockResolvedValue([]);
  vi.mocked(api.listRuns).mockResolvedValue([]);
  vi.mocked(api.listMaterials).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
});

describe("ProjectOverviewPage decision-brief error states (Audit-2026-09-02 F19)", () => {
  it("renders an error state in the literature card when the P1 phase-view query fails", async () => {
    // P1 rejects; P2 stays pending so it contributes no UI of its own.
    vi.mocked(api.getPhaseView).mockImplementation((_projectId, phase) =>
      phase === "P1"
        ? Promise.reject(new Error("network down"))
        : new Promise(() => {}),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Decision brief is unavailable")).toBeInTheDocument();
    });
    expect(screen.getByText("network down")).toBeInTheDocument();
  });

  it("renders an error state in the methods panel when the P2 phase-view query fails", async () => {
    vi.mocked(api.getPhaseView).mockImplementation((_projectId, phase) =>
      phase === "P2"
        ? Promise.reject(new Error("network down"))
        : new Promise(() => {}),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Decision brief is unavailable")).toBeInTheDocument();
    });
  });

  it("renders no error state when the phase-view queries succeed without briefs", async () => {
    // No-brief case stays silent: queries pending (no brief data, no error).
    vi.mocked(api.getPhaseView).mockImplementation(() => new Promise(() => {}));

    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Test project")).toBeInTheDocument();
    });
    expect(screen.queryByText("Decision brief is unavailable")).not.toBeInTheDocument();
  });
});

describe("reduced-motion coverage (Audit-2026-09-02 F20)", () => {
  // Under the jsdom environment import.meta.url is not a file: URL, so
  // resolve from the vitest project root (web/) instead.
  const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf8");

  function reducedMotionBlocks(text: string): string {
    const blocks: string[] = [];
    const marker = /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{/g;
    for (const match of text.matchAll(marker)) {
      let depth = 1;
      let i = match.index + match[0].length;
      const start = i;
      while (i < text.length && depth > 0) {
        if (text[i] === "{") depth += 1;
        else if (text[i] === "}") depth -= 1;
        i += 1;
      }
      blocks.push(text.slice(start, i - 1));
    }
    return blocks.join("\n");
  }

  it("actually reads styles.css and finds a reduced-motion block", () => {
    expect(css.length).toBeGreaterThan(10000);
    expect(reducedMotionBlocks(css).length).toBeGreaterThan(0);
  });

  it("the reduced-motion blocks cover .phase-chip and .tl-dot transitions", () => {
    const blocks = reducedMotionBlocks(css);
    expect(blocks).toContain(".phase-chip");
    expect(blocks).toContain(".tl-dot");
  });

  it("the reduced-motion blocks neutralize the .tl-dot hover scale", () => {
    const blocks = reducedMotionBlocks(css);
    expect(blocks).toMatch(/\.tl-track\s+\.tl-dot:hover/);
  });
});
