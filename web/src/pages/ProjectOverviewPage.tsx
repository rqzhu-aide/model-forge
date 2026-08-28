import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  DecisionBrief,
  MethodRow,
  PhaseId,
  PhaseView,
  ProjectOverview,
  RunLifecycleProjection,
  RunSummary,
  ScientificStatus,
} from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { MaterialShelf } from "../components/MaterialShelf";
import { Panel } from "../components/Panel";
import { getPhaseWorkspaceStatus } from "../components/ProjectWorkspaceTabs";
import { StatusPill } from "../components/Status";
import { NotFoundPage } from "./NotFoundPage";

/* ── Helpers ───────────────────────────────────────────────────────── */

function runRecoverySummary(run: RunSummary): RunLifecycleProjection["recovery_summary"] | undefined {
  return run.lifecycle_projection?.recovery_summary;
}

// A run awaiting output correction is a completed execution whose output
// failed conformance checks — it is NOT an executor failure (HV-3.5).
function isCorrectionRequired(run: RunSummary): boolean {
  return runRecoverySummary(run) === "needs_output_correction";
}

function isTerminalFailure(run: RunSummary): boolean {
  const recovery = runRecoverySummary(run);
  if (recovery) return recovery === "failed" || recovery === "rejected";
  // Fallback for responses without the lifecycle projection: keep the old
  // state-axis behavior.
  return run.state === "failed" || run.state === "rejected";
}

function runStatusLabel(run: RunSummary): string {
  return isCorrectionRequired(run) ? "correction required" : run.state;
}

function phaseStatusTone(tone: ReturnType<typeof getPhaseWorkspaceStatus>["tone"]) {
  if (tone === "current") return "positive" as const;
  if (tone === "attention") return "warning" as const;
  if (tone === "running") return "information" as const;
  return "neutral" as const;
}

function phaseProgressLabel(status: ScientificStatus | undefined): string {
  if (!status || status.record_position === "none") return "—";
  if (status.scientific_outcome === "supported") return "✓";
  if (status.scientific_outcome === "partially_supported") return "~";
  if (status.scientific_outcome === "contradicted") return "✗";
  if (status.attention === "blocking") return "!";
  if (status.record_position === "current") return "…";
  return "—";
}

function phaseProgressTone(status: ScientificStatus | undefined): "positive" | "warning" | "danger" | "neutral" {
  if (!status || status.record_position === "none") return "neutral";
  if (status.scientific_outcome === "supported") return "positive";
  if (status.scientific_outcome === "contradicted") return "danger";
  if (status.attention === "blocking") return "danger";
  if (status.record_position === "current") return "warning";
  return "neutral";
}

function phaseProgressTitle(phase: string, status: ScientificStatus | undefined): string {
  if (!status || status.record_position === "none") return `${phase}: not started`;
  const parts: string[] = [];
  if (status.record_position === "current") parts.push("Record exists");
  if (status.scientific_outcome && status.scientific_outcome !== "not_assessed")
    parts.push(status.scientific_outcome.replace(/_/g, " "));
  if (status.attention && status.attention !== "none") parts.push(status.attention.replace(/_/g, " "));
  return `${phase}: ${parts.join(", ") || "in progress"}`;
}

/* ── Panel 1: Literature at a glance (P1 only) ─────────────────────── */

function LiteratureCard({ p1Phase, overview, basePath }: {
  p1Phase: PhaseView | undefined;
  overview: ProjectOverview;
  basePath: string;
}) {
  const p1Nav = overview.phases.find((p) => p.phase_id === "P1");
  const status = p1Nav ? getPhaseWorkspaceStatus("P1", overview) : null;
  const refs = overview.literature_summary?.source_count;
  const openQuestions = p1Nav?.assessment.attention_count ?? 0;
  const decision = p1Phase?.decision_brief;

  return (
    <Panel
      eyebrow="Phase 1"
      title="Literature at a glance"
      actions={<Link to={`${basePath}/phases/P1`}>Open Phase 1</Link>}
    >
      <div className="lit-glance">
        <div className="lit-glance__stats">
          {refs != null ? (
            <div className="lit-glance__stat">
              <span className="lit-glance__number">{refs}</span>
              <span className="lit-glance__label">references</span>
            </div>
          ) : null}
          {openQuestions > 0 ? (
            <div className="lit-glance__stat">
              <span className="lit-glance__number lit-glance__number--warn">{openQuestions}</span>
              <span className="lit-glance__label">open questions</span>
            </div>
          ) : null}
          {p1Nav ? (
            <StatusPill tone={status ? phaseStatusTone(status.tone) : "neutral"}>
              {status?.label ?? p1Nav.navigation_state}
            </StatusPill>
          ) : (
            <span className="muted-text">Not started</span>
          )}
        </div>
        {decision ? (
          <p className="lit-glance__headline">{decision.headline}</p>
        ) : null}
      </div>
    </Panel>
  );
}

/* ── Panel 2: Method catalog (P2) ──────────────────────────────────── */

function CompactMethodTable({ methods }: { methods: MethodRow[] }) {
  return (
    <div className="table-scroll" role="region" aria-label="Method catalog" tabIndex={0}>
      <table className="compact-method-table">
        <thead>
          <tr>
            <th scope="col">Method</th>
            <th scope="col">Status</th>
            <th scope="col">Theory</th>
            <th scope="col">Evidence</th>
            <th scope="col">Draft</th>
          </tr>
        </thead>
        <tbody>
          {methods.map((method) => (
            <tr key={`${method.identity.stable_id}-${method.identity.version}`}>
              <th scope="row" className="compact-method-table__name">
                {method.display_name}
              </th>
              <td>
                <StatusPill tone={method.lifecycle_state === "active" ? "positive" : "neutral"}>
                  {method.lifecycle_state}
                </StatusPill>
              </td>
              {(["P3", "P4", "P5"] as PhaseId[]).map((phase) => {
                const st = method.phase_statuses[phase];
                return (
                  <td key={phase} className="compact-method-table__progress">
                    <span
                      className={`phase-progress phase-progress--${phaseProgressTone(st)}`}
                      title={phaseProgressTitle(phase, st)}
                    >
                      {phaseProgressLabel(st)}
                    </span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function P2DecisionBrief({ decision }: { decision: DecisionBrief | undefined }) {
  if (!decision) return null;
  return (
    <div className="p2-decision-brief">
      <p className="p2-decision-brief__headline">{decision.headline}</p>
      {decision.principal_uncertainty ? (
        <p className="p2-decision-brief__uncertainty">
          <strong>Key uncertainty:</strong> {decision.principal_uncertainty}
        </p>
      ) : null}
    </div>
  );
}

/* ── Panel 3: Decisions needed (blocking attention items only) ─────── */

function DecisionsNeeded({ overview, basePath }: {
  overview: ProjectOverview;
  basePath: string;
}) {
  const blocking = overview.attention_items.filter(
    (item) => item.severity === "blocking",
  );

  return (
    <Panel
      title="Decisions needed"
      eyebrow="Action required"
    >
      {blocking.length > 0 ? (
        <ul className="attention-list attention-list--compact">
          {blocking.slice(0, 5).map((item) => (
            <li key={item.attention_id} data-severity={item.severity}>
              <div>
                <StatusPill tone="danger">{item.severity.replaceAll("_", " ")}</StatusPill>
                {item.phase ? (
                  <Link to={`${basePath}/phases/${item.phase}`}>
                    <strong>{item.phase}</strong>
                  </Link>
                ) : null}
              </div>
              <p>{item.question}</p>
            </li>
          ))}
          {blocking.length > 5 ? (
            <li className="muted-text">+ {blocking.length - 5} more blocking issue(s)</li>
          ) : null}
        </ul>
      ) : (
        <p className="muted-text">No blocking issues. The project can proceed.</p>
      )}
    </Panel>
  );
}

/* ── Panel 4: Run timeline (longitudinal history) ──────────────────── */

const PHASE_NAMES: Record<string, string> = {
  P1: "Literature",
  P2: "Methods",
  P3: "Theory",
  P4: "Evidence",
  P5: "Manuscript",
};

function RunTimeline({ runs, basePath }: {
  runs: RunSummary[];
  basePath: string;
}) {
  if (runs.length === 0) {
    return (
      <Panel eyebrow="History" title="Run timeline">
        <EmptyState title="No runs yet">
          <p>Launch a phase to see the timeline populate.</p>
        </EmptyState>
      </Panel>
    );
  }

  // Group by phase, in canonical order
  const phases = ["P1", "P2", "P3", "P4", "P5"] as PhaseId[];
  const byPhase = new Map<PhaseId, RunSummary[]>();
  for (const p of phases) byPhase.set(p, []);
  for (const run of runs) {
    const arr = byPhase.get(run.phase) ?? [];
    arr.push(run);
    byPhase.set(run.phase, arr);
  }

  // Compute global time range for positioning
  const timestamps = runs.map((r) => r.requested_at).sort();
  const minMs = new Date(timestamps[0]!).getTime();
  const maxMs = new Date(timestamps[timestamps.length - 1]!).getTime();
  const span = Math.max(maxMs - minMs, 1);

  function positionPct(iso: string): number {
    return ((new Date(iso).getTime() - minMs) / span) * 100;
  }

  function dotClass(run: RunSummary): string {
    if (run.state === "published") return "tl-published";
    if (run.state === "conflicted") return "tl-conflicted";
    if (isCorrectionRequired(run)) return "tl-correction";
    if (isTerminalFailure(run)) return "tl-failed";
    if (run.state === "cancelled") return "tl-cancelled";
    return "tl-running";
  }

  const activePhases = phases.filter((p) => (byPhase.get(p)?.length ?? 0) > 0);
  const published = runs.filter((r) => r.state === "published").length;
  const failed = runs.filter(isTerminalFailure).length;
  const correctionRequired = runs.filter(isCorrectionRequired).length;

  // Recent events: last 5 runs by time, newest first
  const recent = [...runs]
    .sort((a, b) => new Date(b.requested_at).getTime() - new Date(a.requested_at).getTime())
    .slice(0, 5);

  function formatTime(iso: string): string {
    return iso.slice(0, 16).replace("T", " ");
  }

  return (
    <Panel
      eyebrow="History"
      title="Run timeline"
    >
      <div className="timeline-legend">
        <span><i className="tl-dot tl-published" /> Published</span>
        <span><i className="tl-dot tl-failed" /> Failed / rejected</span>
        <span><i className="tl-dot tl-correction" /> Correction required</span>
        <span><i className="tl-dot tl-conflicted" /> Conflicted</span>
        <span><i className="tl-dot tl-cancelled" /> Cancelled</span>
        <span><i className="tl-dot tl-running" /> Running</span>
        <span className="timeline-count">
          {runs.length} runs · {published} published · {failed} failed
          {correctionRequired > 0 ? ` · ${correctionRequired} correction required` : ""}
        </span>
      </div>
      <div className="timeline-chart">
        {activePhases.map((phase) => {
          const phaseRuns = byPhase.get(phase)!;
          return (
            <div className="tl-row" key={phase}>
              <div className="tl-label">
                <Link to={`${basePath}/phases/${phase}`}>{phase} {PHASE_NAMES[phase]}</Link>
              </div>
              <div className="tl-track">
                {phaseRuns.map((run, i) => (
                  <Link
                    to={`${basePath}/runs/${run.run_id}`}
                    className={`tl-dot ${dotClass(run)}`}
                    style={{ left: `${positionPct(run.requested_at)}%` }}
                    key={run.run_id}
                    title={`Run ${i + 1} · ${run.mode} · ${runStatusLabel(run)} · ${formatTime(run.requested_at)}`}
                  />
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <div className="timeline-events">
        <p className="section-kicker">Recent</p>
        {recent.map((run) => (
          <div className="tl-event" key={run.run_id}>
            <time className="tl-event-time">{formatTime(run.requested_at)}</time>
            <span className="tl-event-text">
              <strong>{run.phase} {PHASE_NAMES[run.phase]}</strong>: {runStatusLabel(run)}
            </span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

/* ── Main page ─────────────────────────────────────────────────────── */

export function ProjectOverviewPage() {
  const { projectId } = useParams();
  const overviewQuery = useQuery({
    queryKey: ["overview", projectId],
    queryFn: () => api.getProjectOverview(projectId as string),
    enabled: Boolean(projectId),
  });
  const methodsQuery = useQuery({
    queryKey: ["methods", projectId],
    queryFn: () => api.listMethods(projectId as string),
    enabled: Boolean(projectId),
  });
  const runsQuery = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns(projectId as string),
    enabled: Boolean(projectId),
  });
  // Fetch P1 and P2 phase views for decision briefs
  const p1Query = useQuery({
    queryKey: ["phase", projectId, "P1", "overview"],
    queryFn: () => api.getPhaseView(projectId as string, "P1"),
    enabled: Boolean(projectId),
  });
  const p2Query = useQuery({
    queryKey: ["phase", projectId, "P2", "overview"],
    queryFn: () => api.getPhaseView(projectId as string, "P2"),
    enabled: Boolean(projectId),
  });

  if (!projectId) return <NotFoundPage />;
  if (overviewQuery.isLoading) return <LoadingState label="Loading project state..." />;
  if (overviewQuery.error) return <ErrorState error={overviewQuery.error} title="Project state is unavailable" />;
  if (!overviewQuery.data) return <NotFoundPage />;

  const overview = overviewQuery.data;
  const basePath = `/projects/${encodeURIComponent(projectId)}`;

  // First-run guidance: nothing published anywhere yet → offer the start.
  const noProgressYet =
    overview.phases.length > 0 &&
    overview.phases.every((p) => p.navigation_state === "no_current_record") &&
    overview.active_runs.length === 0;

  return (
    <div className="page-stack project-overview-page">
      <header className="page-header project-heading">
        <div>
          <p className="eyebrow">Project {overview.project.project_id}</p>
          <h1>{overview.project.name}</h1>
          <p className="research-question">{overview.project_brief.research_question}</p>
        </div>
        <Link to={`${basePath}/settings/profiles`} className="button button--quiet">Profiles and skills</Link>
      </header>

      {noProgressYet ? (
        <div className="start-here-banner" role="region" aria-label="Start your study">
          <div>
            <p className="eyebrow">Get started</p>
            <h2>Start Phase 1 — Literature basis</h2>
            <p>
              Phase 1 builds the literature corpus and the first synthesis of
              what is known, disputed, and missing for your question. Every
              later phase builds on it.
            </p>
          </div>
          <Link to={`${basePath}/phases/P1`} className="button button--primary">
            Open Phase 1
          </Link>
        </div>
      ) : null}

      {/* Panel 1: Literature at a glance (P1 only) */}
      <LiteratureCard p1Phase={p1Query.data} overview={overview} basePath={basePath} />

      {/* Panel 2: Method catalog (P2) + decision brief */}
      <Panel
        eyebrow="Method catalog"
        title="Methods and their status"
        description="Each method with its current theory, evidence, and manuscript phase status."
        actions={<Link to={`${basePath}/phases/P2`}>Open Phase 2</Link>}
      >
        {methodsQuery.isLoading ? <LoadingState label="Loading methods..." /> : null}
        {methodsQuery.error ? <ErrorState error={methodsQuery.error} title="Methods are unavailable" /> : null}
        {methodsQuery.data && methodsQuery.data.length > 0 ? (
          <>
            <CompactMethodTable methods={methodsQuery.data} />
            <P2DecisionBrief decision={p2Query.data?.decision_brief} />
          </>
        ) : methodsQuery.data && methodsQuery.data.length === 0 ? (
          <EmptyState title="The method catalog is empty">
            <p>Phase 2 can propose feasible methods after the literature basis is available.</p>
          </EmptyState>
        ) : null}
      </Panel>

      {/* Panel 2b: researcher-supplied supplementary material shelf (ADR-019) */}
      <MaterialShelf projectId={projectId} />

      {/* Panel 3: Run timeline (full width) */}
      {runsQuery.isLoading ? (
        <Panel eyebrow="History" title="Run timeline">
          <LoadingState label="Loading runs..." />
        </Panel>
      ) : runsQuery.error ? (
        <Panel eyebrow="History" title="Run timeline">
          <ErrorState error={runsQuery.error} title="Runs are unavailable" />
        </Panel>
      ) : (
        <RunTimeline runs={runsQuery.data ?? []} basePath={basePath} />
      )}

      {/* Panel 4: Decisions needed */}
      <DecisionsNeeded overview={overview} basePath={basePath} />

      {/* Collapsible details */}
      <details className="overview-details">
        <summary>Project brief and storage details</summary>
        <Panel
          eyebrow="Shared scientific context"
          title="Project brief"
          actions={<Link to={`${basePath}/settings/brief`}>Edit brief</Link>}
        >
          <h3>Research question</h3>
          <p>{overview.project_brief.research_question}</p>
          <h3>Scope</h3>
          <p>{overview.project_brief.scope}</p>
          <h3>Decision criteria</h3>
          <ul>{overview.project_brief.decision_criteria.map((c) => <li key={c}>{c}</li>)}</ul>
          <h3>Scientific constraints</h3>
          <ul>{overview.project_brief.constraints.map((c) => <li key={c}>{c}</li>)}</ul>
        </Panel>
      </details>
    </div>
  );
}
