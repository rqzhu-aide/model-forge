// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type {
  RoleDefinitionView,
  SupervisedRunDetail,
  SupervisedRunSummary,
} from "../api/types";
import { formatDate } from "../utils/format";
import {
  SUPERVISED_RUN_POLL_INTERVAL_MS,
  SupervisedRunsPage,
  buildSupervisedRunRequest,
  supervisedRunsPollInterval,
} from "./SupervisedRunsPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getSupervisedRuns: vi.fn(),
      getRoleDefinitions: vi.fn(),
      startSupervisedRun: vi.fn(),
    },
  };
});

function summary(overrides: Partial<SupervisedRunSummary> = {}): SupervisedRunSummary {
  return {
    invocation_id: "inv-1",
    seal_id: "seal-1",
    role: "research_lead",
    phase: "P2",
    method_identity: null,
    memory_policy: "persistent",
    sealed_at: "2026-08-04T10:00:00Z",
    latest_launch_status: "succeeded",
    validation_verdict: "pass",
    promoted: true,
    ...overrides,
  };
}

function roleDefinition(overrides: Partial<RoleDefinitionView> = {}): RoleDefinitionView {
  return {
    role_id: "research_lead",
    display_name: "Research lead",
    profile_version: "3.1",
    default_profile: "research-lead",
    applicable_phases: ["P1", "P2", "P3", "P4"],
    soul_text: "You are the research lead.",
    soul_sha256: "a".repeat(64),
    base_configuration: {
      file_name: "research_lead.yaml",
      format: "yaml",
      content_sha256: "b".repeat(64),
    },
    recommended_skills: [],
    custom_skills: [],
    library_guidance: {
      file_name: "library_guidance.md",
      content_sha256: "c".repeat(64),
    },
    ...overrides,
  };
}

function detail(overrides: Partial<SupervisedRunDetail> = {}): SupervisedRunDetail {
  return {
    invocation_id: "inv-test-1",
    seal_id: "seal-abc",
    project_id: "project-1",
    role: "research_lead",
    sealed_at: "2026-08-05T09:00:00Z",
    manifest: null,
    manifest_note: null,
    preflight_report: null,
    preflight_note: null,
    launches: [
      {
        launch_id: "launch-1",
        status: "running",
        exit_code: null,
        external_execution_id: null,
        task_brief_sha256: null,
        launched_at: "2026-08-05T09:00:01Z",
        closed_at: null,
      },
    ],
    validation: null,
    promotions: [],
    ...overrides,
  };
}

let queryClient: QueryClient;

function mockQueries(runs: SupervisedRunSummary[] = [summary({})]): void {
  vi.mocked(api.getSupervisedRuns).mockResolvedValue(runs);
  vi.mocked(api.getRoleDefinitions).mockResolvedValue({ roles: [roleDefinition()] });
}

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/projects/project-1/supervised"]}>
        <Routes>
          <Route path="/projects/:projectId/supervised" element={<SupervisedRunsPage />} />
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
  vi.useRealTimers();
});

describe("SupervisedRunsPage list", () => {
  it("renders invocation rows with launch status, verdict, promotion, and policy", async () => {
    mockQueries([
      summary({ invocation_id: "inv-running", latest_launch_status: "running", validation_verdict: null, promoted: false }),
      summary({
        invocation_id: "inv-passed",
        latest_launch_status: "succeeded",
        validation_verdict: "pass",
        promoted: true,
        phase: "P3",
        method_identity: { stable_id: "m_estimator", version: 2 },
        sealed_at: "2026-08-04T10:00:00Z",
      }),
      summary({
        invocation_id: "inv-failed",
        latest_launch_status: "failed",
        validation_verdict: "fail",
        promoted: false,
        memory_policy: "read_only",
        phase: null,
      }),
      summary({
        invocation_id: "inv-sealed-only",
        latest_launch_status: null,
        validation_verdict: null,
        promoted: false,
      }),
    ]);

    renderPage();

    expect(await screen.findByText("inv-running")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("Not launched")).toBeInTheDocument();
    expect(screen.getByText("Validation passed")).toBeInTheDocument();
    expect(screen.getByText("Validation failed")).toBeInTheDocument();
    expect(screen.getByText("Promoted")).toBeInTheDocument();
    expect(screen.getByText("m_estimator, v2")).toBeInTheDocument();
    expect(screen.getByText("P3")).toBeInTheDocument();
    expect(
      screen.getAllByText(`Memory persistent · Sealed ${formatDate("2026-08-04T10:00:00Z")}`).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/Memory read_only/)).toBeInTheDocument();
  });

  it("links every invocation row to its detail page", async () => {
    mockQueries([
      summary({ invocation_id: "inv-link" }),
      summary({ invocation_id: "inv-link-2", latest_launch_status: "running" }),
    ]);

    renderPage();

    const link = await screen.findByRole("link", { name: "inv-link" });
    expect(link).toHaveAttribute("href", "/projects/project-1/supervised/inv-link");
    expect(screen.getByRole("link", { name: "inv-link-2" })).toHaveAttribute(
      "href",
      "/projects/project-1/supervised/inv-link-2",
    );
  });

  it("shows an empty state when the project has no supervised runs", async () => {
    mockQueries([]);

    renderPage();

    expect(await screen.findByText("No supervised runs")).toBeInTheDocument();
  });

  it("renders ErrorState when the list query fails", async () => {
    vi.mocked(api.getSupervisedRuns).mockRejectedValue(new Error("backend down"));

    renderPage();

    expect(await screen.findByText("Supervised runs are unavailable")).toBeInTheDocument();
    expect(screen.getByText("backend down")).toBeInTheDocument();
  });
});

describe("supervised run polling", () => {
  it("sets the interval while any invocation is non-terminal and stops once all are terminal", () => {
    expect(
      supervisedRunsPollInterval([summary({ latest_launch_status: "running" })]),
    ).toBe(SUPERVISED_RUN_POLL_INTERVAL_MS);
    expect(supervisedRunsPollInterval([summary({ latest_launch_status: null })])).toBe(
      SUPERVISED_RUN_POLL_INTERVAL_MS,
    );
    expect(
      supervisedRunsPollInterval([
        summary({ latest_launch_status: "succeeded" }),
        summary({ latest_launch_status: "cancelled" }),
      ]),
    ).toBe(false);
    expect(supervisedRunsPollInterval([summary({ latest_launch_status: "failed" })])).toBe(false);
    expect(supervisedRunsPollInterval([])).toBe(false);
    expect(supervisedRunsPollInterval(undefined)).toBe(false);
  });

  it("refetches the list on the poll interval while a run is running and stops once terminal", async () => {
    vi.useFakeTimers();
    const list = vi.mocked(api.getSupervisedRuns)
      .mockResolvedValueOnce([
        summary({ invocation_id: "inv-poll", latest_launch_status: "running" }),
      ])
      .mockResolvedValueOnce([
        summary({ invocation_id: "inv-poll", latest_launch_status: "running" }),
      ])
      .mockResolvedValue([
        summary({ invocation_id: "inv-poll", latest_launch_status: "succeeded" }),
      ]);

    renderPage();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(list).toHaveBeenCalledTimes(1);
    expect(screen.getByText("inv-poll")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SUPERVISED_RUN_POLL_INTERVAL_MS);
    });
    expect(list).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SUPERVISED_RUN_POLL_INTERVAL_MS);
    });
    // vi.waitFor interleaves fake-timer advancement with retries, which is
    // what the refetch -> cache-update -> rerender chain needs.
    await vi.waitFor(() => {
      expect(list).toHaveBeenCalledTimes(3);
      expect(screen.getByText("Succeeded")).toBeInTheDocument();
    });

    // All rows terminal: no further refetches.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SUPERVISED_RUN_POLL_INTERVAL_MS * 3);
    });
    expect(list).toHaveBeenCalledTimes(3);
  });
});

describe("SupervisedRunsPage start form", () => {
  it("blocks submission when the research brief is empty", async () => {
    mockQueries();
    const start = vi.mocked(api.startSupervisedRun);
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("inv-1");

    await user.click(screen.getByRole("button", { name: "Start supervised run" }));

    expect(await screen.findByText("The research brief is required.")).toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
  });

  it("starts a supervised run with the exact payload and shows the returned detail", async () => {
    mockQueries();
    const start = vi.mocked(api.startSupervisedRun).mockResolvedValue(detail());
    const list = vi.mocked(api.getSupervisedRuns);
    const user = userEvent.setup();

    renderPage();
    const invocation = await screen.findByLabelText(/Invocation id/);
    await user.clear(invocation);
    await user.type(invocation, "inv-test-1");
    const idempotency = screen.getByLabelText(/Idempotency key/);
    await user.clear(idempotency);
    await user.type(idempotency, "idem-1");
    await user.type(screen.getByLabelText(/Method id/), "m_estimator");
    await user.type(screen.getByLabelText(/Method version/), "2");
    await user.type(screen.getByLabelText(/Research brief/), "Estimate the treatment effect under weak overlap.");
    await user.type(screen.getByLabelText("Expected output 1 id"), "table");
    await user.type(screen.getByLabelText("Expected output 1 path"), "results/table.csv");
    await user.type(screen.getByLabelText("Expected output 1 required fields"), "value, se");

    await user.click(screen.getByRole("button", { name: "Start supervised run" }));

    expect(start).toHaveBeenCalledTimes(1);
    expect(start).toHaveBeenCalledWith("project-1", {
      invocation_id: "inv-test-1",
      idempotency_key: "idem-1",
      role: "research_lead",
      phase: "P2",
      method_identity: { stable_id: "m_estimator", version: 2 },
      brief_text: "Estimate the treatment effect under weak overlap.",
      expected_outputs: [
        { output_id: "table", path: "results/table.csv", required_fields: ["value", "se"] },
      ],
      memory_policy: "persistent",
      timeout_seconds: 1200,
    });

    expect(await screen.findByText("Supervised run started")).toBeInTheDocument();
    expect(screen.getByText("inv-test-1")).toBeInTheDocument();
    expect(screen.getByText("seal-abc")).toBeInTheDocument();
    // The successful start invalidates the list query, which refetches.
    await waitFor(() => expect(list).toHaveBeenCalledTimes(2));
  });

  it("shows the preflight failure with its failed check names on a 409", async () => {
    mockQueries();
    vi.mocked(api.startSupervisedRun).mockRejectedValue(
      new ApiError(
        "Preflight failed for this run; no process was launched: disk_space, role_profile",
        409,
        "SUPERVISED_RUN_PREFLIGHT_FAILED",
        "Resolve the preflight failures and replay the same idempotency key to retry the launch.",
        ["project-1", "inv-test-1"],
        {
          passed: false,
          failed_checks: ["disk_space", "role_profile"],
          warnings: [],
          checks: [],
        },
      ),
    );
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("inv-1");
    await user.type(screen.getByLabelText(/Research brief/), "Test the estimator.");

    await user.click(screen.getByRole("button", { name: "Start supervised run" }));

    expect(await screen.findByText("Preflight failed")).toBeInTheDocument();
    expect(screen.getByText("disk_space")).toBeInTheDocument();
    expect(screen.getByText("role_profile")).toBeInTheDocument();
  });

  it("shows the state-lock conflict message on a 409 lock", async () => {
    mockQueries();
    vi.mocked(api.startSupervisedRun).mockRejectedValue(
      new ApiError(
        "State lock held by invocation inv-other for project-role research_lead.",
        409,
        "SUPERVISED_RUN_LOCKED",
        "Wait for the active run of this project-role to finish before starting another.",
        ["project-1", "research_lead", "inv-other"],
      ),
    );
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("inv-1");
    await user.type(screen.getByLabelText(/Research brief/), "Test the estimator.");

    await user.click(screen.getByRole("button", { name: "Start supervised run" }));

    expect(await screen.findByText("State lock held")).toBeInTheDocument();
    expect(screen.getByText(/State lock held by invocation inv-other/)).toBeInTheDocument();
    expect(
      screen.getByText(/Wait for the active run of this project-role to finish/),
    ).toBeInTheDocument();
  });

  it("renders ErrorState when the start fails for another reason", async () => {
    mockQueries();
    vi.mocked(api.startSupervisedRun).mockRejectedValue(new Error("hermes root missing"));
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("inv-1");
    await user.type(screen.getByLabelText(/Research brief/), "Test the estimator.");

    await user.click(screen.getByRole("button", { name: "Start supervised run" }));

    expect(await screen.findByText("The supervised run was not started")).toBeInTheDocument();
    expect(screen.getByText("hermes root missing")).toBeInTheDocument();
  });
});

describe("supervised run request builder", () => {
  const base = {
    invocationId: "inv-1",
    idempotencyKey: "idem-1",
    role: "research_lead",
    phase: "P2",
    methodId: "",
    methodVersion: "",
    briefText: "Run the estimator.",
    expectedOutputs: [{ outputId: "", path: "", requiredFields: "" }],
    memoryPolicy: "persistent" as const,
    timeoutSeconds: "1200",
  };

  it("omits optional fields when left blank", () => {
    expect(buildSupervisedRunRequest({ ...base, timeoutSeconds: "" })).toEqual({
      request: {
        invocation_id: "inv-1",
        idempotency_key: "idem-1",
        role: "research_lead",
        phase: "P2",
        brief_text: "Run the estimator.",
        expected_outputs: [],
        memory_policy: "persistent",
      },
    });
  });

  it("defaults the method version to 1 when only a method id is given", () => {
    const built = buildSupervisedRunRequest({ ...base, methodId: "m_estimator" });
    expect(built).toEqual({
      request: expect.objectContaining({
        method_identity: { stable_id: "m_estimator", version: 1 },
      }),
    });
  });

  it("rejects a partially filled expected output row", () => {
    const built = buildSupervisedRunRequest({
      ...base,
      expectedOutputs: [{ outputId: "table", path: "", requiredFields: "" }],
    });
    expect(built).toEqual({ problem: "Each expected output needs both an output id and a path." });
  });

  it("rejects an invalid timeout", () => {
    expect(buildSupervisedRunRequest({ ...base, timeoutSeconds: "0" })).toEqual({
      problem: "Timeout seconds must be a positive whole number.",
    });
  });

  it("rejects an empty brief", () => {
    expect(buildSupervisedRunRequest({ ...base, briefText: "   " })).toEqual({
      problem: "The research brief is required.",
    });
  });
});
