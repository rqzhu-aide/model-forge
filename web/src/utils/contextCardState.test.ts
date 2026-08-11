import { describe, expect, it } from "vitest";
import { deriveCardState, summariseGroup } from "./contextCardState";

describe("summariseGroup", () => {
  it("marks a group required when any option is required", () => {
    const summary = summariseGroup([
      { required: true, selected: true },
      { required: false, selected: false },
    ]);
    expect(summary.required).toBe(true);
  });

  it("marks a group as existing when any option is not disabled", () => {
    const summary = summariseGroup([
      { required: false, disabled: true, selected: false },
      { required: false, disabled: false, selected: true },
    ]);
    expect(summary.exists).toBe(true);
  });

  it("treats a fully disabled group as unavailable", () => {
    const summary = summariseGroup([
      { required: false, disabled: true, selected: false },
    ]);
    expect(summary.exists).toBe(false);
  });
});

describe("deriveCardState", () => {
  it("locks required cards checked", () => {
    expect(
      deriveCardState({ required: true, exists: true, allSelected: true }),
    ).toEqual({ checked: true, locked: true, unavailable: false });
  });

  it("greys out optional cards whose record does not exist", () => {
    expect(
      deriveCardState({ required: false, exists: false, allSelected: false }),
    ).toEqual({ checked: false, locked: true, unavailable: true });
  });

  it("keeps existing optional cards toggleable and mirrors selection", () => {
    expect(
      deriveCardState({ required: false, exists: true, allSelected: true }),
    ).toEqual({ checked: true, locked: false, unavailable: false });
    expect(
      deriveCardState({ required: false, exists: true, allSelected: false }),
    ).toEqual({ checked: false, locked: false, unavailable: false });
  });
});
