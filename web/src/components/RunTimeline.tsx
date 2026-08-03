import { useEffect, useState } from "react";
import type { RunDetail, RunEvent, RunStage } from "../api/types";
import { formatDate, isRunActive, shortDigest } from "../utils/format";
import { RunStatePill, StatusPill } from "./Status";

function stageTone(stage: RunStage): "positive" | "warning" | "danger" | "neutral" | "information" {
  if (stage.status === "succeeded") return "positive";
  if (stage.status === "failed") return "danger";
  if (stage.status === "stopping") return "warning";
  if (stage.status === "running") return "information";
  return "neutral";
}

function timestamp(value?: string): number | undefined {
  if (!value) return undefined;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? undefined : parsed;
}

export function formatElapsedTime(milliseconds: number | undefined): string {
  if (milliseconds === undefined || !Number.isFinite(milliseconds) || milliseconds < 0) return "Not recorded";
  const totalSeconds = Math.floor(milliseconds / 1_000);
  const hours = Math.floor(totalSeconds / 3_600);
  const minutes = Math.floor((totalSeconds % 3_600) / 60);
  const seconds = totalSeconds % 60;
  if (hours) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function runElapsedMilliseconds(run: RunDetail, now = Date.now()): number | undefined {
  const startedAt = timestamp(run.requested_at);
  if (startedAt === undefined) return undefined;
  const endedAt = isRunActive(run.state) ? now : timestamp(run.updated_at);
  if (endedAt === undefined) return undefined;
  return Math.max(0, endedAt - startedAt);
}

export function runIsStale(run: RunDetail, now = Date.now()): boolean {
  if (!isRunActive(run.state) || !run.stale_after_seconds) return false;
  const lastSignalAt = timestamp(run.last_event_at ?? run.updated_at);
  if (lastSignalAt === undefined) return false;
  return now - lastSignalAt > run.stale_after_seconds * 1_000;
}

export function RunTimeline({ run }: { run: RunDetail }) {
  const active = isRunActive(run.state);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active]);

  const stale = runIsStale(run, now);

  return (
    <div className="run-timeline">
      <div className="run-timeline__summary">
        <div>
          <p className="eyebrow">Execution state</p>
          <RunStatePill state={run.state} />
        </div>
        <div>
          <span>Mode</span>
          <strong>{run.mode}</strong>
        </div>
        <div>
          <span>Elapsed</span>
          <strong>{formatElapsedTime(runElapsedMilliseconds(run, now))}</strong>
        </div>
        <div>
          <span>Last update</span>
          <strong>{formatDate(run.updated_at)}</strong>
        </div>
        {active ? (
          <div>
            <span>Activity signal</span>
            <strong>
              <StatusPill tone={stale ? "warning" : "positive"}>
                {stale ? "No recent signal" : "Within expected interval"}
              </StatusPill>
            </strong>
          </div>
        ) : null}
      </div>
      <ol className="stage-timeline" aria-label="Run stage progress">
        {run.stage_plan.map((stage) => (
          <li key={`${stage.sequence}-${stage.stage_id}`} data-state={stage.status}>
            <span className="stage-timeline__line" aria-hidden="true" />
            <span className="stage-timeline__number" aria-hidden="true">{stage.sequence}</span>
            <div className="stage-timeline__body">
              <div>
                <strong>{stage.label}</strong>
                <StatusPill tone={stageTone(stage)}>{stage.status}</StatusPill>
              </div>
              <p>{stage.roles.join(" + ")} · {stage.execution}</p>
              {stage.activity && <p className="stage-timeline__activity">{stage.activity}</p>}
              <small>
                {stage.started_at ? `Started ${formatDate(stage.started_at)}` : "Not started"}
                {stage.completed_at ? ` · completed ${formatDate(stage.completed_at)}` : ""}
                {!stage.completed_at && stage.last_heartbeat_at ? ` · last signal ${formatDate(stage.last_heartbeat_at)}` : ""}
              </small>
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function RunEventList({ events }: { events: RunEvent[] }) {
  if (!events.length) return <p className="muted-text">No progress event has been reported.</p>;
  return (
    <ol className="event-list" reversed>
      {[...events].reverse().map((event) => (
        <li key={event.event_id}>
          <time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time>
          <div>
            <strong>{event.message}</strong>
            <span>
              Event {event.sequence}
              {event.stage_id ? ` · ${event.stage_id}` : ""}
              {event.role ? ` · ${event.role}` : ""}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function FrozenBasis({ run }: { run: RunDetail }) {
  return (
    <dl className="basis-list">
      <div>
        <dt>Phase contract</dt>
        <dd>{run.contract.phase_contract_version} · <code title={run.contract.phase_contract_sha256}>{shortDigest(run.contract.phase_contract_sha256)}</code></dd>
      </div>
      {run.frozen_basis.map((basis) => (
        <div key={`${basis.label}-${basis.identity}`}>
          <dt>{basis.label}</dt>
          <dd>{basis.identity}<br /><code title={basis.digest}>{shortDigest(basis.digest)}</code></dd>
        </div>
      ))}
    </dl>
  );
}
