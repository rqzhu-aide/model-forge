import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { RunSummary } from "../api/types";
import { latestRunId, RunList } from "./RunList";

const runs: RunSummary[] = [
  {
    run_id: "run-current",
    phase: "P3",
    mode: "p3.develop",
    state: "published",
    requested_at: "2026-08-01T12:00:00Z",
    updated_at: "2026-08-01T12:30:00Z",
    actions: [],
  },
  {
    run_id: "run-latest-failed",
    phase: "P3",
    mode: "p3.develop",
    state: "failed",
    requested_at: "2026-08-02T12:00:00Z",
    updated_at: "2026-08-02T12:10:00Z",
    actions: [],
  },
];

describe("RunList", () => {
  it("separates the latest attempt from the source of the current formal result", () => {
    expect(latestRunId(runs)).toBe("run-latest-failed");
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <RunList
          projectId="project-1"
          runs={runs}
          formalSourceRunId="run-current"
          markLatestAttempt
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("Latest attempt");
    expect(markup).toContain("Current formal source");
    expect(markup).toContain("This attempt did not replace the current formal result.");
  });
});
