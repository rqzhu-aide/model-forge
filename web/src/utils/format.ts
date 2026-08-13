import type { PhaseId, RunLifecycleProjection, RunLifecycleState } from "../api/types";

export const phaseNames: Record<PhaseId, string> = {
  P1: "Literature basis",
  P2: "Method catalog",
  P3: "Theory development",
  P4: "Empirical evaluation",
  P5: "Manuscript assembly",
};

export const phaseShortNames: Record<PhaseId, string> = {
  P1: "Literature",
  P2: "Methods",
  P3: "Theory",
  P4: "Evidence",
  P5: "Manuscript",
};

export function formatDate(value?: string): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function shortDigest(value?: string): string {
  if (!value) return "Not recorded";
  return value.length > 16 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
}

export function formatSize(bytes: number | undefined | null): string | null {
  if (bytes == null) return null;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function sentenceCase(value: string): string {
  const text = value.replaceAll("_", " ").replaceAll(".", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function isRunActive(
  state: RunLifecycleState,
  recoverySummary?: RunLifecycleProjection["recovery_summary"],
): boolean {
  // A run awaiting output correction (recovery_summary =
  // "needs_output_correction") is no longer executing even though its state
  // machine label is a terminal "failed"/"rejected". Every terminal recovery
  // summary means the run is not active; only "in_progress" keeps it active.
  // When no projection is available we fall back to the state axis alone.
  if (recoverySummary && recoverySummary !== "in_progress") return false;
  return [
    "created",
    "preparing",
    "prepared",
    "running",
    "cancellation_requested",
    "submitted",
    "validating",
    "promoting",
    "correction_authorized",
    "correcting",
  ].includes(state);
}
