import type { ReactNode } from "react";
import type {
  ConfigurationAssetStatus,
  ConfigurationOverallStatus,
  RunLifecycleProjection,
  RunLifecycleState,
  ScientificStatus,
} from "../api/types";
import { sentenceCase } from "../utils/format";

export type Tone = "positive" | "warning" | "danger" | "neutral" | "information";

const runLabels: Record<RunLifecycleState, string> = {
  created: "Created",
  preparing: "Preparing",
  prepared: "Prepared",
  running: "Running",
  cancellation_requested: "Cancellation requested",
  submitted: "Submitted",
  validating: "Validating",
  promoting: "Publishing",
  published: "Published",
  failed: "Execution failed",
  rejected: "Validation rejected",
  conflicted: "Publication conflict",
  cancelled: "Cancelled",
  correction_authorized: "Correction authorized",
  correcting: "Correcting output",
  correction_exhausted: "Correction exhausted",
};

export function runStateTone(state: RunLifecycleState): Tone {
  if (state === "published") return "positive";
  if (state === "failed" || state === "rejected") return "danger";
  if (state === "correction_exhausted") return "warning";
  if (state === "conflicted" || state === "cancellation_requested") return "warning";
  if (
    [
      "created",
      "preparing",
      "prepared",
      "running",
      "submitted",
      "validating",
      "promoting",
      "correction_authorized",
      "correcting",
    ].includes(state)
  ) {
    return "information";
  }
  return "neutral";
}

export function configurationOverallTone(status: ConfigurationOverallStatus): Tone {
  if (status === "healthy") return "positive";
  if (status === "unavailable") return "danger";
  return "warning";
}

export function configurationAssetTone(status: ConfigurationAssetStatus): Tone {
  if (status === "present") return "positive";
  if (status === "customized") return "warning";
  if (status === "missing") return "danger";
  return "neutral";
}

export function StatusPill({
  children,
  tone = "neutral",
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  title?: string;
}) {
  return (
    <span className="status-pill" data-tone={tone} title={title}>
      <span className="status-pill__marker" aria-hidden="true" />
      {children}
    </span>
  );
}

export function RunStatePill({
  state,
  recoverySummary,
}: {
  state: RunLifecycleState;
  recoverySummary?: RunLifecycleProjection["recovery_summary"];
}) {
  // A run awaiting output correction completed its execution — the state axis
  // label ("failed"/"rejected") would misrepresent it as an execution failure.
  // Show the projection-aware label instead (HV-3.4).
  if (recoverySummary === "needs_output_correction") {
    return <StatusPill tone="neutral">Output needs correction</StatusPill>;
  }
  return <StatusPill tone={runStateTone(state)}>{runLabels[state]}</StatusPill>;
}

const statusLabels = {
  publication: {
    run_local: "Run-local work",
    submitted: "Submitted",
    validated: "Validated",
    formal: "Formal record",
    invalid: "Invalid",
  },
  position: {
    current: "Current",
    historical: "Earlier record",
    none: "No current slot",
  },
  alignment: {
    exact: "Exact current basis",
    compatible: "Assessed compatible",
    unassessed: "Not yet reassessed",
    outdated: "Uses an earlier basis",
    not_applicable: "Not applicable",
  },
  attention: {
    none: "No open attention",
    monitor: "Monitor",
    reassessment_required: "Reassessment required",
    blocking: "Blocks dependent use",
  },
  outcome: {
    supported: "Supported under stated assumptions",
    partially_supported: "Partially supported",
    contradicted: "Contradicted",
    inconclusive: "Inconclusive",
    not_assessed: "Not yet assessed",
    not_applicable: "Not applicable",
  },
} as const;

function alignmentTone(value?: ScientificStatus["alignment"]): Tone {
  if (value === "exact" || value === "compatible") return "positive";
  if (value === "unassessed" || value === "outdated") return "warning";
  return "neutral";
}

function attentionTone(value?: ScientificStatus["attention"]): Tone {
  if (value === "blocking") return "danger";
  if (value === "monitor" || value === "reassessment_required") return "warning";
  if (value === "none") return "positive";
  return "neutral";
}

function outcomeTone(value?: ScientificStatus["scientific_outcome"]): Tone {
  if (value === "supported" || value === "partially_supported") return "positive";
  if (value === "contradicted") return "danger";
  if (value === "inconclusive") return "warning";
  return "neutral";
}

export interface CompactScientificStatusSummary {
  stateLabel: string;
  stateTone: Tone;
  attentionLabel?: string;
  attentionTone?: Tone;
  outcomeLabel: string;
  outcomeTone: Tone;
}

export function compactScientificStatusSummary(
  status: ScientificStatus | undefined,
): CompactScientificStatusSummary {
  if (!status) {
    return {
      stateLabel: "Not run",
      stateTone: "neutral",
      outcomeLabel: "Outcome not assessed",
      outcomeTone: "neutral",
    };
  }

  let stateLabel = "Status recorded";
  let stateTone: Tone = "neutral";
  if (status.alignment === "outdated") {
    stateLabel = "Outdated";
    stateTone = "warning";
  } else if (status.alignment === "unassessed") {
    stateLabel = "Unassessed";
    stateTone = "warning";
  } else if (status.record_position === "current") {
    stateLabel = "Current";
    stateTone = "positive";
  } else if (status.record_position === "historical") {
    stateLabel = "Earlier record";
  } else if (status.publication_state === "formal") {
    stateLabel = "Formal record";
    stateTone = "positive";
  } else if (status.publication_state === "invalid") {
    stateLabel = "Invalid";
    stateTone = "danger";
  } else if (status.alignment === "exact" || status.alignment === "compatible") {
    stateLabel = "Current basis";
    stateTone = "positive";
  }

  const attention = status.attention;
  const attentionLabel = attention && attention !== "none"
    ? `Attention: ${statusLabels.attention[attention]}`
    : undefined;
  const outcome = status.scientific_outcome;
  const outcomeLabel = outcome ? statusLabels.outcome[outcome] : "Outcome not recorded";
  return {
    stateLabel,
    stateTone,
    ...(attentionLabel ? {
      attentionLabel,
      attentionTone: attentionTone(attention),
    } : {}),
    outcomeLabel,
    outcomeTone: outcomeTone(outcome),
  };
}

/**
 * Outcome-text dedupe (phase-tab redesign, 2026-08-21): the outcome words
 * only render when they add information beyond the status pills. "Not yet
 * assessed" / "Outcome not recorded" repeat what the pill already says (or
 * the absence of an outcome), so they never render as text; an informative
 * outcome like "Supported under stated assumptions" stays visible.
 */
function outcomeTextIsInformative(status: ScientificStatus | undefined): boolean {
  const outcome = status?.scientific_outcome;
  return outcome !== undefined && outcome !== "not_assessed" && outcome !== "not_applicable";
}

export function CompactPhaseStatus({ status }: { status: ScientificStatus | undefined }) {
  const summary = compactScientificStatusSummary(status);
  const showOutcome = outcomeTextIsInformative(status);
  const accessibleParts = [
    summary.stateLabel,
    summary.attentionLabel,
    showOutcome ? `Scientific outcome: ${summary.outcomeLabel}` : undefined,
  ].filter(Boolean);
  return (
    <span
      className="compact-phase-status"
      aria-label={`${accessibleParts.join(". ")}.`}
    >
      <StatusPill tone={summary.stateTone}>{summary.stateLabel}</StatusPill>
      {summary.attentionLabel ? (
        <span className="compact-phase-status__attention">
          <StatusPill tone={summary.attentionTone ?? "neutral"}>{summary.attentionLabel}</StatusPill>
        </span>
      ) : null}
      {showOutcome ? (
        <span className="compact-phase-status__outcome" data-tone={summary.outcomeTone}>
          {summary.outcomeLabel}
        </span>
      ) : null}
    </span>
  );
}
