/**
 * Tier 1 — Compact phase status summary.
 *
 * Answers: "Where does this phase stand?" in at most ~5 elements.
 * Shows: status pill, scientific outcome, decision-brief headline, key dates.
 * Deliberately does NOT show: hashes, digests, role resources, 5-dimension grid.
 */
import type { PhaseView } from "../api/types";
import { formatDate } from "../utils/format";
import {
  CompactPhaseStatus,
  compactScientificStatusSummary,
} from "./Status";

export function PhaseStatusCard({ phase }: { phase: PhaseView }) {
  const record = phase.current_record;
  const summary = compactScientificStatusSummary(phase.assessment);

  return (
    <section className="phase-status-card" aria-label="Current phase status">
      <div className="phase-status-card__header">
        <CompactPhaseStatus status={phase.assessment} />
      </div>

      {phase.decision_brief ? (
        <div className="phase-status-card__decision">
          <p className="phase-status-card__decision-label">Latest assessment</p>
          <p className="phase-status-card__decision-text">
            {phase.decision_brief.current_decision}
          </p>
        </div>
      ) : record ? (
        <div className="phase-status-card__decision">
          <p className="phase-status-card__decision-label">Current result</p>
          <p className="phase-status-card__decision-text">{record.summary}</p>
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
