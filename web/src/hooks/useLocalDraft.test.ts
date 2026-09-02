// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DraftStorage } from "./useLocalDraft";
import { readDraft, runInstructionDraftKey, useLocalDraft, writeDraft } from "./useLocalDraft";

function memoryStorage(): DraftStorage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value); },
    removeItem: (key) => { values.delete(key); },
  };
}

describe("run instruction draft storage", () => {
  it("uses a project and phase-specific key", () => {
    expect(runInstructionDraftKey("study/one", "P3")).toBe("model-forge:run-instructions:v1:study%2Fone:P3");
  });

  it("persists exact instruction text and removes an empty draft", () => {
    const storage = memoryStorage();
    const key = runInstructionDraftKey("study", "P4");
    writeDraft(storage, key, "Check the finite-sample regime.\nKeep n fixed.");
    expect(readDraft(storage, key)).toBe("Check the finite-sample regime.\nKeep n fixed.");
    writeDraft(storage, key, "   ");
    expect(readDraft(storage, key)).toBe("");
  });
});

describe("useLocalDraft external application", () => {
  it("a same-value applyExternal does not swallow the next genuine edit (F21)", () => {
    window.localStorage.clear();
    const key = runInstructionDraftKey("study", "P1");
    const { result } = renderHook(() => useLocalDraft(key));

    act(() => result.current.setValue("original"));
    expect(readDraft(window.localStorage, key)).toBe("original");

    // Same-value apply: React bails out of the state write, so the skip
    // flag must not be armed - otherwise the NEXT genuine edit is dropped.
    act(() => result.current.applyExternal("original"));
    act(() => result.current.setValue("edited"));
    expect(readDraft(window.localStorage, key)).toBe("edited");
  });

  it("a changed-value applyExternal is not persisted as the user's draft", () => {
    window.localStorage.clear();
    const key = runInstructionDraftKey("study", "P2");
    const { result } = renderHook(() => useLocalDraft(key));

    act(() => result.current.applyExternal("from a rerun prefill"));
    expect(readDraft(window.localStorage, key)).toBe("");

    act(() => result.current.setValue("my own edit"));
    expect(readDraft(window.localStorage, key)).toBe("my own edit");
  });
});
