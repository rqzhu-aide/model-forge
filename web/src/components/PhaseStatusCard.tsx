/**
 * Tier 1 — Compact phase status summary ("verdict strip" layout, 2026-08-21).
 *
 * Answers: "Where does this phase stand?" in at most ~5 elements.
 * Layout (approved redesign): the status chips form ONE horizontal strip
 * across the top of the card — never a vertical side column — and the
 * assessment paragraph spans the full card width below them, clamped to
 * 3 lines with a More/Less expander. Key dates/runs stay a compact footer
 * line. Deliberately does NOT show: hashes, digests, role resources,
 * 5-dimension grid.
 */
import { useLayoutEffect, useRef, useState } from "react";
import type { PhaseView } from "../api/types";
import { formatDate } from "../utils/format";
import {
  CompactPhaseStatus,
  compactScientificStatusSummary,
} from "./Status";

function ClampedDecisionText({ text }: { text: string }) {
  const paragraphRef = useRef<HTMLParagraphElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useLayoutEffect(() => {
    const el = paragraphRef.current;
    // Measure with the clamp forced on, independent of the current expanded
    // state, so a text change is always re-measured from the clamped layout.
    // jsdom has no layout (both heights are 0), so no expander renders there.
    if (!el) return;
    el.setAttribute("data-clamped", "");
    setOverflows(el.scrollHeight > el.clientHeight + 1);
    setExpanded(false);
  }, [text]);

  return (
    <>
      <p
        ref={paragraphRef}
        className="phase-status-card__decision-text"
        data-clamped={expanded ? undefined : ""}
      >
        {text}
      </p>
      {overflows ? (
        <button
          type="button"
          className="phase-status-card__expander"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Less" : "More"}
        </button>
      ) : null}
    </>
  );
}

export function PhaseStatusCard({ phase }: { phase: PhaseView }) {
  const record = phase.current_record;
  const summary = compactScientificStatusSummary(phase.assessment);

  const decisionText = phase.decision_brief
    ? phase.decision_brief.current_decision
    : record
      ? record.summary
      : undefined;
  const decisionLabel = phase.decision_brief
    ? "Latest assessment"
    : record
      ? "Current result"
      : undefined;

  return (
    <section className="phase-status-card" aria-label="Current phase status">
      <div className="phase-status-card__header">
        <CompactPhaseStatus status={phase.assessment} />
      </div>

      {decisionText !== undefined ? (
        <div className="phase-status-card__decision">
          <p className="phase-status-card__decision-label">{decisionLabel}</p>
          <ClampedDecisionText text={decisionText} />
        </div>
      ) : (
        <div className="phase-status-card__decision">
          <p className="phase-status-card__decision-text muted-text">
            {phase.empty_state_message ?? "No result has been published yet."}
          </p>
        </div>
      )}

      <dl className="phase-status-card__meta">
        {record ? (
          <>
            <div>
              <dt>Published</dt>
              <dd>{formatDate(record.published_at)}</dd>
            </div>
            <div>
              <dt>Outcome</dt>
              <dd>{summary.outcomeLabel}</dd>
            </div>
          </>
        ) : (
          <div>
            <dt>Runs</dt>
            <dd>{phase.recent_runs.length} attempt(s)</dd>
          </div>
        )}
        {phase.active_runs.length > 0 ? (
          <div>
            <dt>Active</dt>
            <dd>{phase.active_runs.length} run(s) in progress</dd>
          </div>
        ) : null}
      </dl>
    </section>
  );
}
