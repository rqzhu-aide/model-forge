import { useCallback, useEffect, useRef, useState } from "react";

export interface DraftStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function browserStorage(): DraftStorage | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

export function runInstructionDraftKey(projectId: string, phaseId: string): string {
  return `model-forge:run-instructions:v1:${encodeURIComponent(projectId)}:${phaseId}`;
}

export function readDraft(storage: DraftStorage | undefined, key: string): string {
  if (!storage) return "";
  try {
    return storage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

export function writeDraft(storage: DraftStorage | undefined, key: string, value: string): void {
  if (!storage) return;
  try {
    if (value.trim()) storage.setItem(key, value);
    else storage.removeItem(key);
  } catch {
    // Draft persistence is a convenience and must never block run configuration.
  }
}

export function useLocalDraft(key: string) {
  const [initialDraft] = useState(() => readDraft(browserStorage(), key));
  const [value, setValue] = useState(initialDraft);
  const skipPersist = useRef(false);

  useEffect(() => {
    // An externally applied value (e.g. a rerun prefill) must not overwrite
    // the user's own stored draft; the next genuine edit resumes persistence.
    if (skipPersist.current) {
      skipPersist.current = false;
      return;
    }
    writeDraft(browserStorage(), key, value);
  }, [key, value]);

  const clear = useCallback(() => {
    const storage = browserStorage();
    try {
      storage?.removeItem(key);
    } catch {
      // A failed cleanup must not turn a completed launch into a UI error.
    }
    setValue("");
  }, [key]);

  const applyExternal = useCallback((next: string) => {
    skipPersist.current = true;
    setValue(next);
  }, []);

  return {
    value,
    setValue,
    clear,
    applyExternal,
    restored: Boolean(initialDraft.trim()),
  };
}
