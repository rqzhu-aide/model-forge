import { describe, expect, it } from "vitest";
import { runEventTransport } from "./useRunEvents";

describe("run event transport label", () => {
  it("shows a recorded snapshot for terminal runs regardless of prior stream state", () => {
    expect(runEventTransport(false, true)).toBe("Recorded snapshot");
    expect(runEventTransport(false, false)).toBe("Recorded snapshot");
  });

  it("distinguishes live and polling transport for active runs", () => {
    expect(runEventTransport(true, true)).toBe("Live stream");
    expect(runEventTransport(true, false)).toBe("Polling");
  });
});
