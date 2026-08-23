import { describe, expect, it } from "vitest";
import type { DraftStorage } from "./useLocalDraft";
import { readDraft, runInstructionDraftKey, writeDraft } from "./useLocalDraft";

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
