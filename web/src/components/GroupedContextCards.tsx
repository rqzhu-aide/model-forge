import { useMemo, useState } from "react";
import type { ContextOption } from "../api/types";
import { GroupFeedbackModal } from "./GroupFeedbackModal";
import { deriveCardState, summariseGroup } from "../utils/contextCardState";
import { formatSize } from "../utils/format";

const GROUP_LABELS: Record<string, string> = {
  brief: "Project brief",
  literature: "Literature review",
  catalog: "Method catalog",
  theory: "Theory results",
  empirical: "Empirical results",
  manuscript: "Manuscript draft",
  decision: "Phase decisions",
  other: "Other context",
};

const GROUP_ORDER: string[] = [
  "brief",
  "literature",
  "catalog",
  "theory",
  "empirical",
  "manuscript",
  "decision",
  "other",
];

interface GroupedContextCardsProps {
  options: ContextOption[];
  projectId: string;
  selectedIds: ReadonlySet<string>;
  onToggle: (optionId: string, checked: boolean) => void;
}

export function GroupedContextCards({
  options,
  projectId,
  selectedIds,
  onToggle,
}: GroupedContextCardsProps) {
  const groups = useMemo(() => buildGroups(options), [options]);

  const toggleGroup = (group: ContextGroup, checked: boolean) => {
    for (const opt of group.options) {
      if (opt.required || opt.disabled) continue;
      onToggle(opt.option_id, checked);
    }
  };

  return (
    <div className="context-cards">
      {groups.map((group) => (
        <GroupCard
          key={group.key}
          group={group}
          projectId={projectId}
          selectedIds={selectedIds}
          onToggleGroup={(checked) => toggleGroup(group, checked)}
        />
      ))}
    </div>
  );
}

interface ContextGroup {
  key: string;
  options: ContextOption[];
}

function GroupCard({
  group,
  projectId,
  selectedIds,
  onToggleGroup,
}: {
  group: ContextGroup;
  projectId: string;
  selectedIds: ReadonlySet<string>;
  onToggleGroup: (checked: boolean) => void;
}) {
  const [modalOpen, setModalOpen] = useState(false);

  const cardState = deriveCardState(
    summariseGroup(
      group.options.map((o) => ({
        required: o.required,
        disabled: o.disabled,
        selected: selectedIds.has(o.option_id),
      })),
    ),
  );

  const totalSize = group.options.reduce((sum, o) => sum + (o.size_bytes ?? 0), 0);
  const sizeText = totalSize > 0 ? formatSize(totalSize) : null;
  const label = GROUP_LABELS[group.key] ?? group.key;

  // Merge summaries: take the first non-null feedback as the collapsed preview
  // Collect feedback with source info so we can prefer synthesis for lit.
  const summaries = group.options
    .filter((o): o is typeof o & { feedback: string } =>
      o.feedback != null && o.feedback.length > 0,
    )
    .map((o) => ({ optionId: o.option_id, text: o.feedback }));
  // Merge summaries: for literature, prefer synthesis; otherwise take the
  // first non-null feedback as the collapsed preview.
  const previewSummary = pickPreviewSummary(group.key, summaries);

  return (
    <>
      <div
        className={
          "context-card" +
          (cardState.unavailable ? " context-card--unavailable" : "")
        }
      >
        <div className="context-card__header">
          <label className="context-card__check">
            <input
              type="checkbox"
              checked={cardState.checked}
              disabled={cardState.locked}
              onChange={(e) => onToggleGroup(e.target.checked)}
            />
            {sizeText ? (
              <span className="context-card__size">{sizeText}</span>
            ) : null}
          </label>
          {summaries.length > 0 ? (
            <button
              type="button"
              className="context-card__expand"
              onClick={() => setModalOpen(true)}
            >
              more
            </button>
          ) : null}
        </div>
        <div className="context-card__body">
          <strong>{label}</strong>
          <small className="context-card__desc">
            {group.options.length > 1
              ? `${group.options.length} records`
              : group.options[0]?.description ?? ""}
          </small>
          {previewSummary ? (
            <em className="context-card__feedback">{previewSummary}</em>
          ) : null}
        </div>
      </div>
      {modalOpen ? (
        <GroupFeedbackModal
          group={group}
          label={label}
          projectId={projectId}
          onClose={() => setModalOpen(false)}
        />
      ) : null}
    </>
  );
}

function buildGroups(options: ContextOption[]): ContextGroup[] {
  const visible = options.filter((o) => !o.hidden && o.group !== "brief");
  const buckets = new Map<string, ContextOption[]>();
  for (const option of visible) {
    const key = option.group ?? "other";
    const list = buckets.get(key);
    if (list) list.push(option);
    else buckets.set(key, [option]);
  }

  const groups: ContextGroup[] = [];
  for (const [key, opts] of buckets) {
    groups.push({ key, options: opts });
  }

  groups.sort((a, b) => {
    const ai = GROUP_ORDER.indexOf(a.key);
    const bi = GROUP_ORDER.indexOf(b.key);
    if (ai === -1 && bi === -1) return a.key.localeCompare(b.key);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });

  return groups;
}

interface SummaryEntry {
  optionId: string;
  text: string;
}

/**
 * Pick the preview summary for a collapsed card. For the literature group,
 * prefer the synthesis record. For all other groups, take the first entry.
 */
function pickPreviewSummary(groupKey: string, entries: SummaryEntry[]): string | null {
  if (entries.length === 0) return null;
  if (groupKey === "literature") {
    const synth = entries.find((e) => e.optionId.includes("synthesis"));
    if (synth) return synth.text;
  }
  return entries[0]?.text ?? null;
}
