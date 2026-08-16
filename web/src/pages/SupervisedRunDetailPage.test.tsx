// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type {
  SupervisedLaunchRecord,
  SupervisedManifestSummary,
  SupervisedPromotionRecord,
  SupervisedRunDetail,
  SupervisedValidationReport,
} from "../api/types";
import { shortDigest } from "../utils/format";
import {
  formatElapsedTime,
  smallestSafeNextAction,
  supervisedRunDetailPollInterval,
} from "./SupervisedRunDetailPage";
import { SupervisedRunDetailPage } from "./SupervisedRunDetailPage";
import { SUPERVISED_RUN_POLL_INTERVAL_MS } from "./SupervisedRunsPage";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getSupervisedRun: vi.fn(),
      cancelSupervisedRun: vi.fn(),
    },
  };
});

const PREFLIGHT_CHECK_NAMES = [
  "hermes_executable",
  "role_assets",
  "selected_state",
  "paths_permissions",
  "free_space",
  "lock_ownership",
  "task_brief",
  "output_contract",
];

function launchRecord(overrides: Partial<SupervisedLaunchRecord> = {}): SupervisedLaunchRecord {
  return {
    launch_id: "launch-1",
    status: "succeeded",
    exit_code: 0,
    external_execution_id: "hermes-kanban:exec-20260805-090001-7f3a9c2e81b4d5f6a7b8c9d0e1f2a3b4",
    task_brief_sha256: "b".repeat(64),
    launched_at: "2026-08-05T09:00:01Z",
    closed_at: "2026-08-05T09:05:31Z",
    ...overrides,
  };
}

function manifest(overrides: Partial<SupervisedManifestSummary> = {}): SupervisedManifestSummary {
  return {
    project_id: "project-1",
    role: "research_lead",
    phase: "P2",
    method_identity: { stable_id: "m_estimator", version: 2 },
    memory_snapshot: {
      policy: "persistent",
      identity: "a".repeat(64),
      digest: "b".repeat(64),
      source: "/home/hermes/profiles/project-1-research_lead/memories",
    },
    session_snapshot: {
      procedure: "sqlite_backup_v1",
      source: "/home/hermes/profiles/project-1-research_lead/state.db",
      quiescent: true,
      sha256: "c".repeat(64),
    },
    expected_outputs: [
      { output_id: "table", path: "results/table.csv", required_fields: ["value", "se"] },
      { output_id: "figure", path: "results/figure.png" },
    ],
    hermes: {
      executable: "/home/hermes/.local/bin/hermes",
      version: "0.9.0 (build 2026-07-01)",
    },
    role_asset_digests: {
      "soul.md": "1".repeat(64),
      "base.yaml": "2".repeat(64),
      "library_guidance.md": "3".repeat(64),
    },
    sealed_at: "2026-08-05T09:00:00Z",
    ...overrides,
  };
}

function validationReport(
  overrides: Partial<SupervisedValidationReport> = {},
): SupervisedValidationReport {
  return {
    launch_id: "launch-1",
    verdict: "pass",
    validated_at: "2026-08-05T09:06:00Z",
    checks: [
      { name: "declared_outputs_present", status: "pass", detail: "2 of 2 declared outputs found" },
      { name: "required_fields_complete", status: "pass", detail: "all required fields present" },
    ],
    ...overrides,
  };
}

function promotionRecord(
  overrides: Partial<SupervisedPromotionRecord> = {},
): SupervisedPromotionRecord {
  return {
    record_id: "promo-1",
    promoted_at: "2026-08-05T09:07:00Z",
    status: "succeeded",
    before_digest: { memories: null, "state.db": "c".repeat(64) },
    after_digest: { memories: "d".repeat(64), "state.db": "e".repeat(64) },
    backup_paths: {
      memories: "/backups/promo-1/memories",
      "state.db": "/backups/promo-1/state.db",
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
    manifest: manifest(),
    manifest_note: null,
    preflight_report: {
      report_id: "preflight-1",
      verdict: "pass",
      created_at: "2026-08-05T09:00:05Z",
      checks: [
        { name: "hermes_executable", status: "pass", detail: "hermes 0.9.0 at /home/hermes/.local/bin/hermes" },
        { name: "role_assets", status: "pass", detail: "3 assets verified against the manifest" },
        { name: "selected_state", status: "pass", detail: "memories digest matches (identity='fresh')" },
        { name: "paths_permissions", status: "pass", detail: "run directories exist with expected permissions" },
        { name: "free_space", status: "pass", detail: "1.2 GiB free on the run volume" },
        { name: "lock_ownership", status: "pass", detail: "state lock held by this invocation" },
        { name: "task_brief", status: "pass", detail: "task brief is a non-empty regular file" },
        { name: "output_contract", status: "fail", detail: "expected output 'results/table.csv' already exists" },
      ],
    },
    preflight_note: null,
    launches: [launchRecord()],
    validation: null,
    promotions: [],
    ...overrides,
  };
}

let queryClient: QueryClient;

function renderPage() {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/projects/project-1/supervised/inv-test-1"]}>
        <Routes>
          <Route
            path="/projects/:projectId/supervised/:invocationId"
            element={<SupervisedRunDetailPage />}
          />
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

describe("SupervisedRunDetailPage sealed basis", () => {
  it("renders the manifest summary: role, phase, method, memory, session, hermes, outputs, digests", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(detail());

    renderPage();

    expect(await screen.findByText("Sealed basis")).toBeInTheDocument();
    expect(screen.getByText("research_lead")).toBeInTheDocument();
    expect(screen.getByText("P2")).toBeInTheDocument();
    expect(screen.getByText("m_estimator, v2")).toBeInTheDocument();
    expect(screen.getByText("persistent")).toBeInTheDocument();
    expect(screen.getByText("a".repeat(64))).toBeInTheDocument();
    expect(
      screen.getByText(/source: \/home\/hermes\/profiles\/project-1-research_lead\/memories/),
    ).toBeInTheDocument();
    expect(screen.getByText("sqlite_backup_v1")).toBeInTheDocument();
    expect(
      screen.getByText((content) =>
        content.includes(`sha256 ${shortDigest("c".repeat(64))}`),
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/source: \/home\/hermes\/profiles\/project-1-research_lead\/state.db/),
    ).toBeInTheDocument();
    expect(screen.getByText("results/table.csv")).toBeInTheDocument();
    expect(screen.getByText("Required fields: value, se")).toBeInTheDocument();
    expect(screen.getByText("/home/hermes/.local/bin/hermes")).toBeInTheDocument();
    expect(screen.getByText("0.9.0 (build 2026-07-01)")).toBeInTheDocument();
    expect(screen.getByText("soul.md")).toBeInTheDocument();
    expect(screen.getByText(shortDigest("1".repeat(64)))).toBeInTheDocument();
    // Only three digests: rendered inline, not collapsed.
    expect(screen.queryByText("3 role asset digests")).not.toBeInTheDocument();
  });

  it("shows the manifest note when the stored manifest is unreadable", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(
      detail({
        manifest: null,
        manifest_note: "The stored manifest JSON is unreadable or fails digest verification.",
      }),
    );

    renderPage();

    expect(await screen.findByText("Sealed basis unavailable")).toBeInTheDocument();
    expect(screen.getByText(/unreadable or fails digest verification/)).toBeInTheDocument();
  });

  it("collapses long role asset digest lists behind a summary", async () => {
    const digests: Record<string, string> = {};
    for (let i = 0; i < 6; i += 1) digests[`asset-${i}.md`] = `${i}`.repeat(64);
    vi.mocked(api.getSupervisedRun).mockResolvedValue(
      detail({ manifest: manifest({ role_asset_digests: digests }) }),
    );

    renderPage();

    expect(await screen.findByText("6 role asset digests")).toBeInTheDocument();
    expect(screen.getByText("asset-5.md")).toBeInTheDocument();
  });
});

describe("SupervisedRunDetailPage preflight", () => {
  it("renders the eight named checks with pass/fail pills and details", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(detail());

    renderPage();

    expect(await screen.findByText("Preflight passed")).toBeInTheDocument();
    for (const name of PREFLIGHT_CHECK_NAMES) {
      expect(screen.getByText(name)).toBeInTheDocument();
    }
    expect(screen.getAllByText("Pass")).toHaveLength(7);
    expect(screen.getAllByText("Fail")).toHaveLength(1);
    expect(screen.getByText(/already exists/)).toBeInTheDocument();
    expect(
      screen.getByText(/3 assets verified against the manifest/),
    ).toBeInTheDocument();
  });

  it("shows the null note when the run never recorded a preflight", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(
      detail({
        preflight_report: null,
        preflight_note:
          "No preflight report was recorded for this run: the start command persists reports, so a sealed-but-never-started invocation (or one started before preflight persistence) has none.",
      }),
    );

    renderPage();

    expect(await screen.findByText("No preflight report")).toBeInTheDocument();
    expect(screen.getByText(/sealed-but-never-started/)).toBeInTheDocument();
    expect(screen.queryByText("hermes_executable")).not.toBeInTheDocument();
  });
});

describe("SupervisedRunDetailPage launches", () => {
  it("renders every launch record: status, exit code, durable id, digest, timestamps, elapsed", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(
      detail({
        launches: [
          launchRecord({ launch_id: "launch-1", status: "succeeded" }),
          launchRecord({
            launch_id: "launch-2",
            status: "failed",
            exit_code: 3,
            external_execution_id: "exec-2",
            task_brief_sha256: "f".repeat(64),
            launched_at: "2026-08-05T10:00:00Z",
            closed_at: "2026-08-05T10:02:15Z",
          }),
        ],
      }),
    );

    renderPage();

    expect(await screen.findByText("launch-1")).toBeInTheDocument();
    expect(screen.getByText("launch-2")).toBeInTheDocument();
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("5m 30s")).toBeInTheDocument();
    expect(screen.getByText("2m 15s")).toBeInTheDocument();
    const durableId = screen.getByTitle(
      "hermes-kanban:exec-20260805-090001-7f3a9c2e81b4d5f6a7b8c9d0e1f2a3b4",
    );
    expect(durableId).toHaveTextContent(
      "hermes-kanban:exec-20260805-090001-7f3a9c2e81b4d5f6a7b8c9d0e1f2a3b4",
    );
    expect(screen.getByTitle("f".repeat(64))).toHaveTextContent(shortDigest("f".repeat(64)));
  });

  it("shows an empty state when the invocation has no launch record", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(detail({ launches: [] }));

    renderPage();

    expect(await screen.findByText("Not launched")).toBeInTheDocument();
  });

  it("hides the cancel button when the latest launch is terminal", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(detail());

    renderPage();
    await screen.findByText("Succeeded");

    expect(screen.queryByRole("button", { name: "Cancel this run" })).not.toBeInTheDocument();
  });
});

describe("SupervisedRunDetailPage cancel", () => {
  it("cancels with one click and shows the returned cancelled detail", async () => {
    const get = vi.mocked(api.getSupervisedRun)
      .mockResolvedValueOnce(detail({ launches: [launchRecord({ status: "running", closed_at: null })] }))
      .mockResolvedValue(
        detail({ launches: [launchRecord({ status: "cancelled", closed_at: "2026-08-05T09:00:11Z" })] }),
      );
    const cancel = vi.mocked(api.cancelSupervisedRun).mockResolvedValue(
      detail({ launches: [launchRecord({ status: "cancelled", closed_at: "2026-08-05T09:00:11Z" })] }),
    );
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Running");

    await user.click(screen.getByRole("button", { name: "Cancel this run" }));

    expect(cancel).toHaveBeenCalledWith("project-1", "inv-test-1");
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    // The returned detail invalidates the detail query, which refetches.
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("button", { name: "Cancel this run" })).not.toBeInTheDocument();
  });

  describe.each([
    [
      "terminal",
      "INVALID_TRANSITION",
      "The supervised run 'inv-test-1' already finished with status 'succeeded'; there is nothing to cancel.",
      "Start a new supervised run if you need another execution.",
    ],
    [
      "not-yet-cancellable",
      "TARGET_STATE_MISMATCH",
      "The supervised run 'inv-test-1' is still starting up; its durable process identity is not recorded yet, so it is not yet cancellable. Retry in a moment.",
      "Retry the cancel once the run is running.",
    ],
  ])("409 %s", (_label, code, message, correction) => {
    it("shows the returned 409 message", async () => {
      vi.mocked(api.getSupervisedRun).mockResolvedValue(
        detail({ launches: [launchRecord({ status: "running", closed_at: null })] }),
      );
      vi.mocked(api.cancelSupervisedRun).mockRejectedValue(
        new ApiError(message, 409, code, correction, ["project-1", "inv-test-1"]),
      );
      const user = userEvent.setup();

      renderPage();
      await screen.findByText("Running");

      await user.click(screen.getByRole("button", { name: "Cancel this run" }));

      expect(await screen.findByText("Not cancelled")).toBeInTheDocument();
      expect(screen.getByText(message)).toBeInTheDocument();
      expect(screen.getByText(code)).toBeInTheDocument();
      expect(screen.getByText(correction)).toBeInTheDocument();
      // The launch is unchanged and still running.
      expect(screen.getByText("Running")).toBeInTheDocument();
    });
  });

  it("renders ErrorState when the cancel fails for another reason", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(
      detail({ launches: [launchRecord({ status: "running", closed_at: null })] }),
    );
    vi.mocked(api.cancelSupervisedRun).mockRejectedValue(new Error("backend down"));
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Running");

    await user.click(screen.getByRole("button", { name: "Cancel this run" }));

    expect(await screen.findByText("The run was not cancelled")).toBeInTheDocument();
    expect(screen.getByText("backend down")).toBeInTheDocument();
  });
});

describe("SupervisedRunDetailPage closure", () => {
  it("renders the validation verdict with per-check results and promotion targets", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(
      detail({
        validation: validationReport({
          verdict: "fail",
          checks: [
            { name: "declared_outputs_present", status: "pass", detail: "2 of 2 declared outputs found" },
            { name: "required_fields_complete", status: "fail", detail: "missing required field 'se' in results/table.csv" },
          ],
        }),
        promotions: [promotionRecord()],
      }),
    );

    renderPage();

    expect(await screen.findByText("Validation failed")).toBeInTheDocument();
    expect(screen.getByText("declared_outputs_present")).toBeInTheDocument();
    expect(screen.getByText("required_fields_complete")).toBeInTheDocument();
    expect(screen.getByText(/missing required field/)).toBeInTheDocument();
    expect(screen.getByText("required_fields_complete").closest("li")).toHaveClass(
      "checks-list__item--fail",
    );
    expect(screen.getByText("promo-1")).toBeInTheDocument();
    expect(screen.getByText("Promoted")).toBeInTheDocument();
    expect(screen.getByText("memories")).toBeInTheDocument();
    expect(screen.getByText("state.db")).toBeInTheDocument();
    expect(screen.getByText(shortDigest("d".repeat(64)))).toBeInTheDocument();
    expect(screen.getByText(shortDigest("e".repeat(64)))).toBeInTheDocument();
    expect(
      screen.getByText(/Backup: \/backups\/promo-1\/state.db/),
    ).toBeInTheDocument();
  });

  it("shows an explicit nothing-promoted empty state when there are no promotion records", async () => {
    vi.mocked(api.getSupervisedRun).mockResolvedValue(
      detail({ validation: validationReport() }),
    );

    renderPage();

    expect(await screen.findByText("Validation passed")).toBeInTheDocument();
    expect(screen.getByText("Nothing promoted")).toBeInTheDocument();
    expect(screen.getByText(/no promotion records/)).toBeInTheDocument();
  });
});

describe("smallest safe next action", () => {
  describe.each([
    ["never launched", { launches: [] }, "Start this run from the list page"],
    [
      "running",
      { launches: [launchRecord({ status: "running", closed_at: null })] },
      "Wait or cancel",
    ],
    [
      "failed",
      { launches: [launchRecord({ status: "failed" })] },
      "Open the run logs below, then start a new invocation",
    ],
    [
      "cancelled",
      { launches: [launchRecord({ status: "cancelled", exit_code: null })] },
      "Open the run logs below, then start a new invocation",
    ],
    [
      "succeeded with failing validation",
      { launches: [launchRecord({ status: "succeeded" })], validation: validationReport({ verdict: "fail" }) },
      "Review the failed checks; the run changed no state",
    ],
    [
      "succeeded with passed validation and promotions",
      { launches: [launchRecord({ status: "succeeded" })], validation: validationReport(), promotions: [promotionRecord()] },
      "State promoted; the next run sees it",
    ],
    [
      "succeeded with passed validation and no promotions",
      { launches: [launchRecord({ status: "succeeded" })], validation: validationReport() },
      "Outputs valid; policy promotes nothing",
    ],
  ])("%s", (_label, overrides, expectedHint) => {
    it(`shows: ${expectedHint}`, async () => {
      vi.mocked(api.getSupervisedRun).mockResolvedValue(detail(overrides));

      renderPage();

      expect(await screen.findByText(expectedHint)).toBeInTheDocument();
    });
  });

  it("derives the hint from the durable state alone", () => {
    expect(smallestSafeNextAction(detail({ launches: [] }))).toBe(
      "Start this run from the list page",
    );
    expect(
      smallestSafeNextAction(detail({ launches: [launchRecord({ status: "failed" })] })),
    ).toBe("Open the run logs below, then start a new invocation");
  });
});

describe("SupervisedRunDetailPage polling", () => {
  it("sets the interval while any launch is non-terminal and stops once all are terminal", () => {
    expect(
      supervisedRunDetailPollInterval(detail({ launches: [launchRecord({ status: "running" })] })),
    ).toBe(SUPERVISED_RUN_POLL_INTERVAL_MS);
    expect(supervisedRunDetailPollInterval(detail({ launches: [] }))).toBe(
      SUPERVISED_RUN_POLL_INTERVAL_MS,
    );
    expect(
      supervisedRunDetailPollInterval(detail({ launches: [launchRecord({ status: "succeeded" })] })),
    ).toBe(false);
    expect(supervisedRunDetailPollInterval(undefined)).toBe(false);
  });

  it("refetches the detail on the poll interval while a launch is running and stops once terminal", async () => {
    vi.useFakeTimers();
    const running = detail({ launches: [launchRecord({ status: "running", closed_at: null })] });
    const succeeded = detail({ launches: [launchRecord({ status: "succeeded" })] });
    const get = vi.mocked(api.getSupervisedRun)
      .mockResolvedValueOnce(running)
      .mockResolvedValueOnce(running)
      .mockResolvedValue(succeeded);

    renderPage();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(get).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Running")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(SUPERVISED_RUN_POLL_INTERVAL_MS);
    });
    expect(get).toHaveBeenCalledTimes(2);

    // vi.waitFor interleaves fake-timer advancement with retries, which is
    // what the refetch -> cache-update -> rerender chain needs.
    await vi.waitFor(
      () => {
        expect(get).toHaveBeenCalledTimes(3);
        expect(screen.getByText("Succeeded")).toBeInTheDocument();
      },
      { timeout: 5000, interval: 250 },
    );

    // All launches terminal: no further refetches.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SUPERVISED_RUN_POLL_INTERVAL_MS * 3);
    });
    expect(get).toHaveBeenCalledTimes(3);
  });
});

describe("elapsed time formatting", () => {
  it("formats the closed delta and falls back to a dash when unparseable", () => {
    expect(formatElapsedTime("2026-08-05T09:00:01Z", "2026-08-05T09:05:31Z")).toBe("5m 30s");
    expect(formatElapsedTime("2026-08-05T09:00:00Z", "2026-08-05T09:00:45Z")).toBe("45s");
    expect(formatElapsedTime("2026-08-05T09:00:00Z", "2026-08-05T10:15:00Z")).toBe("1h 15m");
    expect(formatElapsedTime("not-a-date", "2026-08-05T09:05:31Z")).toBeUndefined();
    expect(formatElapsedTime("2026-08-05T09:05:31Z", "2026-08-05T09:00:01Z")).toBeUndefined();
  });
});
