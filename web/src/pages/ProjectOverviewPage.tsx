import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { PhaseId } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { ProjectBriefPanel } from "../components/ProjectBriefPanel";
import { getPhaseWorkspaceStatus } from "../components/ProjectWorkspaceTabs";
import { ProjectionNote } from "../components/ProjectionNote";
import { RunList } from "../components/RunList";
import { CompactPhaseStatus, ScientificStatusGrid, StatusPill } from "../components/Status";
import { formatDate } from "../utils/format";
import { NotFoundPage } from "./NotFoundPage";

function phaseStatusTone(tone: ReturnType<typeof getPhaseWorkspaceStatus>["tone"]) {
  if (tone === "current") return "positive" as const;
  if (tone === "attention") return "warning" as const;
  if (tone === "running") return "information" as const;
  return "neutral" as const;
}

export function ProjectOverviewPage() {
  const { projectId } = useParams();
  const overviewQuery = useQuery({
    queryKey: ["overview", projectId],
    queryFn: () => api.getProjectOverview(projectId as string),
    enabled: Boolean(projectId),
  });
  const runsQuery = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => api.listRuns(projectId as string),
    enabled: Boolean(projectId),
  });

  if (!projectId) return <NotFoundPage />;
  if (overviewQuery.isLoading) return <LoadingState label="Loading project state..." />;
  if (overviewQuery.error) return <ErrorState error={overviewQuery.error} title="Project state is unavailable" />;
  if (!overviewQuery.data) return <NotFoundPage />;

  const overview = overviewQuery.data;
  const basePath = `/projects/${encodeURIComponent(projectId)}`;

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

      <ProjectBriefPanel projectId={projectId} brief={overview.project_brief} />

      <Panel
        eyebrow="Research progress"
        title="Phases at a glance"
        description="Each card reports current formal state or an active run. Open a phase to inspect its scientific record and decide whether to run it."
      >
        <div className="phase-progress-grid">
          {overview.phases.map((phase) => {
            const status = getPhaseWorkspaceStatus(phase.phase_id, overview);
            return (
              <Link
                to={`${basePath}/phases/${phase.phase_id}`}
                className="phase-progress-card"
                key={phase.phase_id}
              >
                <div className="phase-progress-card__heading">
                  <div><span>{phase.phase_id}</span><strong>{phase.name}</strong></div>
                  <StatusPill tone={phaseStatusTone(status.tone)}>{status.label}</StatusPill>
                </div>
                <p>{phase.summary}</p>
                <dl>
                  <div><dt>Formal records</dt><dd>{phase.formal_record_count}</dd></div>
                  <div><dt>Method-scoped</dt><dd>{phase.method_scoped_record_count}</dd></div>
                  <div><dt>Active runs</dt><dd>{phase.active_run_count}</dd></div>
                </dl>
                {phase.latest_published_at ? <small>Latest publication {formatDate(phase.latest_published_at)}</small> : null}
              </Link>
            );
          })}
        </div>
      </Panel>

      <div className="overview-grid">
        <Panel
          eyebrow="Phase 1 basis"
          title="Current literature synthesis"
          actions={<Link to={`${basePath}/phases/P1`}>Open Phase 1</Link>}
        >
          {overview.literature_summary ? (
            <div className="record-summary">
              <p>{overview.literature_summary.current_synthesis}</p>
              <p><strong>{overview.literature_summary.source_count}</strong> sources in the current basis</p>
              <p>{overview.literature_summary.coverage_summary}</p>
              <ScientificStatusGrid status={overview.literature_summary.status} />
            </div>
          ) : (
            <EmptyState title="No formal literature basis yet">
              <p>Open Phase 1 to define a search scope and explicitly start the first literature run.</p>
            </EmptyState>
          )}
        </Panel>

        <Panel
          eyebrow="Phase 2 catalog"
          title="Current methods"
          actions={<Link to={`${basePath}/phases/P2`}>Open Phase 2</Link>}
        >
          {overview.methods.length ? (
            <ul className="method-summary-list">
              {overview.methods.map((method) => (
                <li key={`${method.identity.stable_id}-${method.identity.version}`}>
                  <div>
                    <strong>{method.display_name}</strong>
                    <StatusPill>{`v${method.identity.version}`}</StatusPill>
                    <StatusPill>{method.lifecycle_state}</StatusPill>
                  </div>
                  <p>{method.summary}</p>
                  <dl>
                    {(["P3", "P4", "P5"] as PhaseId[]).map((phase) => (
                      <div key={phase}><dt>{phase}</dt><dd><CompactPhaseStatus status={method.phase_statuses[phase]} /></dd></div>
                    ))}
                  </dl>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="The method catalog is empty">
              <p>Phase 2 can propose feasible methods after the literature basis is available.</p>
            </EmptyState>
          )}
        </Panel>
      </div>

      <div className="overview-grid">
        <Panel
          title="Active project runs"
          eyebrow="Current execution"
          description="Only active operations are available in the project overview. Completed run records remain available within their phase."
        >
          <RunList projectId={projectId} runs={overview.active_runs} emptyMessage="No controlled run is active." />
        </Panel>
        <Panel title="Research attention" eyebrow="Questions requiring judgment">
          {overview.attention_items.length ? (
            <ul className="attention-list">
              {overview.attention_items.map((item) => (
                <li key={item.attention_id} data-severity={item.severity}>
                  <div><StatusPill>{item.severity.replaceAll("_", " ")}</StatusPill>{item.phase ? <strong>{item.phase}</strong> : null}</div>
                  <p>{item.question}</p>
                </li>
              ))}
            </ul>
          ) : <p className="muted-text">No open research-attention item is projected.</p>}
        </Panel>
      </div>

      <Panel
        eyebrow="Project history"
        title="Run timeline"
        description="This list retains controlled operations across all phases. Open a run to inspect its frozen inputs, stage history, validation, and publication state."
      >
        {runsQuery.isLoading ? <LoadingState label="Loading project run history..." /> : null}
        {runsQuery.error ? <ErrorState error={runsQuery.error} title="Project run history is unavailable" /> : null}
        {runsQuery.data ? (
          <RunList
            projectId={projectId}
            runs={[...runsQuery.data].sort((left, right) => Date.parse(right.requested_at) - Date.parse(left.requested_at))}
            emptyMessage="No controlled run has been recorded for this project."
            markLatestAttempt
          />
        ) : null}
      </Panel>

      <Panel
        eyebrow="Project files"
        title="Backend-managed storage"
        description="Formal records and run-local work are separated by the storage authority described below."
      >
        <dl className="record-metadata project-storage-details">
          <div><dt>Storage authority</dt><dd>Backend managed</dd></div>
          {overview.storage.display_path ? <div><dt>Project location</dt><dd><code>{overview.storage.display_path}</code></dd></div> : null}
          <div><dt>Open folder</dt><dd>Not available from this web interface</dd></div>
        </dl>
        <p className="muted-text">{overview.storage.explanation}</p>
      </Panel>

      <ProjectionNote projection={overview.projection} />
    </div>
  );
}
