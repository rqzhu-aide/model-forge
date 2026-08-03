import type { ReactNode } from "react";
import type { RunLifecycleState, ScientificStatus } from "../api/types";
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
};

export function runStateTone(state: RunLifecycleState): Tone {
  if (state === "published") return "positive";
  if (state === "failed" || state === "rejected") return "danger";
  if (state === "conflicted" || state === "cancellation_requested") return "warning";
  if (["created", "preparing", "prepared", "running", "submitted", "validating", "promoting"].includes(state)) {
    return "information";
  }
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

export function RunStatePill({ state }: { state: RunLifecycleState }) {
  return <StatusPill tone={runStateTone(state)}>{runLabels[state]}</StatusPill>;
}

const statusLabels = {
  publication: {
    run_local: "Run-local work",
    submitted: "Submitted",
    validated: "Validated",
    formal: "Formal record",
    withdrawn: "Withdrawn",
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

export function ScientificStatusGrid({ status }: { status: ScientificStatus }) {
  const publication = status.publication_state;
  const position = status.record_position;
  const alignment = status.alignment;
  const attention = status.attention;
  const outcome = status.scientific_outcome;

  const value = <T extends string>(entry: Record<T, string>, key?: T) =>
    key ? entry[key] : "Not recorded";

  return (
    <dl className="status-grid">
      <div><dt>Authority</dt><dd>{value(statusLabels.publication, publication)}</dd></div>
      <div><dt>Position</dt><dd>{value(statusLabels.position, position)}</dd></div>
      <div>
        <dt>Method alignment</dt>
        <dd><StatusPill tone={alignmentTone(alignment)}>{value(statusLabels.alignment, alignment)}</StatusPill></dd>
      </div>
      <div>
        <dt>Research attention</dt>
        <dd>
          <StatusPill tone={attentionTone(attention)}>
            {value(statusLabels.attention, attention)}
            {status.attention_count ? ` (${status.attention_count})` : ""}
          </StatusPill>
        </dd>
      </div>
      <div>
        <dt>Scientific outcome</dt>
        <dd><StatusPill tone={outcomeTone(outcome)}>{value(statusLabels.outcome, outcome)}</StatusPill></dd>
      </div>
    </dl>
  );
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
  } else if (status.publication_state === "withdrawn") {
    stateLabel = "Withdrawn";
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

export function CompactPhaseStatus({ status }: { status: ScientificStatus | undefined }) {
  const summary = compactScientificStatusSummary(status);
  const accessibleParts = [
    summary.stateLabel,
    summary.attentionLabel,
    `Scientific outcome: ${summary.outcomeLabel}`,
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
      <span className="compact-phase-status__outcome" data-tone={summary.outcomeTone}>
        {summary.outcomeLabel}
      </span>
    </span>
  );
}

export function UnknownStatus({ value }: { value?: string }) {
  return <span>{value ? sentenceCase(value) : "Not recorded"}</span>;
}
