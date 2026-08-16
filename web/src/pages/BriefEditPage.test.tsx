// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { ProjectBriefView } from "../api/types";
import { BriefEditPage } from "./BriefEditPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getProjectBrief: vi.fn(),
      updateProjectBrief: vi.fn(),
    },
  };
});

function briefView(overrides: Partial<ProjectBriefView> = {}): ProjectBriefView {
  return {
    project_id: "project.test",
    record_id: "record.brief.001",
    generation_id: "generation.001",
    research_question: "Does X predict Y?",
    domains: ["statistics"],
    intended_use: "exploratory",
    scope: "In scope: everything",
    decision_criteria: ["criterion one", "criterion two"],
    constraints: ["constraint one"],
    scope_note: "",
    published_at: "2026-08-15T00:00:00Z",
    artifact: {
      artifact_id: "artifact.brief.001",
      label: "Brief",
      information_layer: "primary" as const,
      href: "/artifacts/artifact.brief.001",
    },
    actions: [
      {
        descriptor_id: "action.update_brief",
        action_type: "update_project_brief" as never,
        enabled: true,
        consequence_summary: "Updates the shared brief",
      },
    ],
    projection: {},
    ...overrides,
  } as ProjectBriefView;
}

function renderPage(projectId = "project.test") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/projects/${projectId}/settings/brief`]}>
        <Routes>
          <Route
            path="projects/:projectId/settings/brief"
            element={<BriefEditPage />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("BriefEditPage", () => {
  it("loads the existing brief into the form", async () => {
    vi.mocked(api.getProjectBrief).mockResolvedValue(briefView());
    renderPage();

    await waitFor(() => {
      expect(screen.getByDisplayValue("Does X predict Y?")).toBeInTheDocument();
    });
    expect(screen.getByDisplayValue("In scope: everything")).toBeInTheDocument();
    expect(screen.getByLabelText(/Decision criteria/)).toHaveValue(
      "criterion one\ncriterion two",
    );
    expect(screen.getByLabelText(/Constraints/)).toHaveValue("constraint one");
  });

  it("saves the edited brief and confirms", async () => {
    vi.mocked(api.getProjectBrief).mockResolvedValue(briefView());
    vi.mocked(api.updateProjectBrief).mockResolvedValue(briefView());
    renderPage();

    const question = await screen.findByLabelText(/Research question/);
    await userEvent.clear(question);
    await userEvent.type(question, "Does Z predict Y?");

    await userEvent.click(screen.getByRole("button", { name: /Save brief/ }));

    await waitFor(() => {
      expect(api.updateProjectBrief).toHaveBeenCalledWith(
        "project.test",
        expect.objectContaining({
          action_descriptor_id: "action.update_brief",
          research_question: "Does Z predict Y?",
        }),
      );
    });
    await waitFor(() => {
      expect(screen.getByText(/Saved/)).toBeInTheDocument();
    });
  });

  it("shows an error state when the brief cannot be loaded", async () => {
    vi.mocked(api.getProjectBrief).mockRejectedValue(new Error("boom"));
    renderPage();

    await waitFor(() => {
      expect(screen.getByText(/unavailable/i)).toBeInTheDocument();
    });
  });
});
