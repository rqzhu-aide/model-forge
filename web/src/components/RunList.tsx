import { Link } from "react-router-dom";
import type { RunLifecycleState, RunSummary } from "../api/types";
import { formatDate } from "../utils/format";
import { RunStatePill } from "./Status";

const UNPUBLISHED_TERMINAL_STATES: RunLifecycleState[] = [
  "failed",
  "rejected",
  "conflicted",
  "cancelled",
];

export function latestRunId(runs: RunSummary[]): string | undefined {
  return runs.reduce<RunSummary | undefined>((latest, run) => {
    if (!latest) return run;
    const runTime = Date.parse(run.requested_at);
    const latestTime = Date.parse(latest.requested_at);
    if (Number.isNaN(runTime)) return latest;
    if (Number.isNaN(latestTime) || runTime > latestTime) return run;
    return latest;
  }, undefined)?.run_id;
}

function latestRelationship(run: RunSummary, formalSourceRunId: string | null | undefined): string | undefined {
  if (run.run_id === formalSourceRunId) return "This run produced the current formal result.";
  if (UNPUBLISHED_TERMINAL_STATES.includes(run.state)) {
    return formalSourceRunId
      ? "This attempt did not replace the current formal result."
      : "This attempt did not publish a formal result.";
  }
  return undefined;
}

export function RunList({
  projectId,
  runs,
  emptyMessage = "No runs are recorded here.",
  formalSourceRunId,
  markLatestAttempt = false,
}: {
  projectId: string;
  runs: RunSummary[];
  emptyMessage?: string;
  formalSourceRunId?: string | null;
  markLatestAttempt?: boolean;
}) {
  if (runs.length === 0) return <p className="muted-text">{emptyMessage}</p>;

  const newestRunId = markLatestAttempt ? latestRunId(runs) : undefined;

  return (
    <ul className="run-list">
      {runs.map((run) => {
        const isLatest = run.run_id === newestRunId;
        const isFormalSource = run.run_id === formalSourceRunId;
        const relationship = isLatest ? latestRelationship(run, formalSourceRunId) : undefined;
        return (
          <li key={run.run_id}>
            <div className="run-list__heading">
              <Link to={`/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(run.run_id)}`}>
                <span className="phase-chip" data-phase={run.phase}>{run.phase}</span> research run
              </Link>
              <RunStatePill
                state={run.state}
                {...(run.lifecycle_projection?.recovery_summary
                  ? { recoverySummary: run.lifecycle_projection.recovery_summary }
                  : {})}
              />
            </div>
            {(isLatest || isFormalSource) ? (
              <div className="run-list__markers" aria-label="Run relationship to current phase state">
                {isLatest ? <span>Latest attempt</span> : null}
                {isFormalSource ? <span>Current formal source</span> : null}
              </div>
            ) : null}
            <p>
              <span>{run.mode}</span>
              {run.method_identity ? <span>{run.method_identity.stable_id}, v{run.method_identity.version}</span> : null}
              {run.current_stage_label ? <span>{run.current_stage_label}</span> : null}
            </p>
            <small>Requested {formatDate(run.requested_at)} · updated {formatDate(run.updated_at)}</small>
            {relationship ? <p className="run-list__relationship">{relationship}</p> : null}
          </li>
        );
      })}
    </ul>
  );
}
