import { describe, expect, it } from "vitest";
import { isRunActive } from "./format";

describe("isRunActive", () => {
  it("treats pre-publication lifecycle states as active", () => {
    expect(isRunActive("created")).toBe(true);
    expect(isRunActive("running")).toBe(true);
    expect(isRunActive("promoting")).toBe(true);
  });

  it("treats terminal states as inactive", () => {
    expect(isRunActive("published")).toBe(false);
    expect(isRunActive("failed")).toBe(false);
    expect(isRunActive("rejected")).toBe(false);
    expect(isRunActive("cancelled")).toBe(false);
  });

  it("treats a run awaiting output correction as inactive even though its state label is failed", () => {
    expect(isRunActive("failed", "needs_output_correction")).toBe(false);
    expect(isRunActive("rejected", "needs_output_correction")).toBe(false);
  });

  it("keeps in-progress recovery active and ignores recovery for non-terminal states", () => {
    expect(isRunActive("running", "in_progress")).toBe(true);
    expect(isRunActive("failed", "in_progress")).toBe(false);
  });

  it("treats correction lifecycle states as active until exhausted", () => {
    expect(isRunActive("correction_authorized")).toBe(true);
    expect(isRunActive("correcting")).toBe(true);
    expect(isRunActive("correction_exhausted")).toBe(false);
    expect(isRunActive("correcting", "in_progress")).toBe(true);
    expect(isRunActive("correction_exhausted", "needs_output_correction")).toBe(false);
  });
});
