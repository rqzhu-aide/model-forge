import { describe, expect, it } from "vitest";
import type { RunDetail } from "../api/types";
import { formatElapsedTime, runElapsedMilliseconds, runIsStale } from "./RunTimeline";

function run(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    run_id: "run-1",
    phase: "P4",
    mode: "p4.preliminary",
    state: "running",
    requested_at: "2026-08-02T12:00:00Z",
    updated_at: "2026-08-02T12:00:20Z",
    requested_by: "researcher",
    instructions: "Evaluate finite-sample error.",
    actions: [],
    contract: {
      phase_contract_version: "1.0",
      phase_contract_sha256: "abcdef",
    },
    frozen_basis: [],
    stage_plan: [],
    last_event_sequence: 1,
    last_event_at: "2026-08-02T12:00:20Z",
    stale_after_seconds: 30,
    ...overrides,
  };
}

describe("run monitoring helpers", () => {
  it("reports a live elapsed interval", () => {
    const now = Date.parse("2026-08-02T13:02:03Z");
    expect(formatElapsedTime(runElapsedMilliseconds(run(), now))).toBe("1h 2m 3s");
  });

  it("uses the terminal update as the elapsed endpoint", () => {
    const published = run({ state: "published", updated_at: "2026-08-02T12:01:05Z" });
    expect(formatElapsedTime(runElapsedMilliseconds(published, Date.parse("2026-08-03T00:00:00Z")))).toBe("1m 5s");
  });

  it("marks only active runs beyond their recorded signal interval as stale", () => {
    expect(runIsStale(run(), Date.parse("2026-08-02T12:00:51Z"))).toBe(true);
    expect(runIsStale(run({ state: "failed" }), Date.parse("2026-08-02T12:00:51Z"))).toBe(false);
  });
});
