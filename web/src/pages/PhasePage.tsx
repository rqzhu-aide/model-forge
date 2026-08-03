import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { PhaseId } from "../api/types";
import { DecisionBrief } from "../components/DecisionBrief";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { MethodSelector, SelectedMethodSummary } from "../components/MethodSelector";
import { MethodTable } from "../components/MethodTable";
import { Panel } from "../components/Panel";
import { ProjectionNote } from "../components/ProjectionNote";
import { RunForm } from "../components/RunForm";
import { RunList } from "../components/RunList";
import { ScientificStatusGrid } from "../components/Status";
import { formatDate, shortDigest } from "../utils/format";
import { NotFoundPage } from "./NotFoundPage";

const validPhases: PhaseId[] = ["P1", "P2", "P3", "P4", "P5"];

function isPhaseId(value: string | undefined): value is PhaseId {
  return validPhases.includes(value as PhaseId);
}

export function PhasePage() {
  const { projectId, phaseId: rawPhaseId } = useParams();
  const phaseId = isPhaseId(rawPhaseId) ? rawPhaseId : undefined;
  const [mode, setMode] = useState("");
  const [selectedMethodId, setSelectedMethodId] = useState("");

  useEffect(() => {
    setMode("");
    setSelectedMethodId("");
  }, [phaseId, projectId]);

  const phaseQuery = useQuery({
    queryKey: ["phase", projectId, phaseId, mode, selectedMethodId],
    queryFn: () => api.getPhaseView(
      projectId as string,
      phaseId as PhaseId,
      {
        ...(mode ? { mode } : {}),
        ...(selectedMethodId ? { methodId: selectedMethodId } : {}),
      },
    ),
    enabled: Boolean(projectId && phaseId),
  });

  const needsMethods = phaseId === "P2" || phaseId === "P3" || phaseId === "P4" || phaseId === "P5";
  const methodsQuery = useQuery({
    queryKey: ["methods", projectId],
    queryFn: () => api.listMethods(projectId as string),
    enabled: Boolean(projectId && needsMethods),
  });

  useEffect(() => {
    const defaultMode = phaseQuery.data?.run_configuration.default_mode;
    if (!mode && defaultMode) setMode(defaultMode);
  }, [mode, phaseQuery.data?.run_configuration.default_mode]);

  if (!projectId || !phaseId) return <NotFoundPage />;
  if (phaseQuery.isLoading) return <LoadingState label={`Loading ${phaseId} state…`} />;
  if (phaseQuery.error) return <ErrorState error={phaseQuery.error} title={`${phaseId} state is unavailable`} />;
  if (!phaseQuery.data) return <NotFoundPage />;

  const phase = phaseQuery.data;
  const methods = methodsQuery.data ?? [];
  const selectedMethod = methods.find((method) => method.identity.stable_id === selectedMethodId);
  const isMethodSelectionPhase = phaseId === "P3" || phaseId === "P4";

  return (
    <div className="page-stack">
      <header className="page-header phase-heading">
        <div>
          <p className="eyebrow">{phaseId} research phase</p>
          <h1>{phase.name}</h1>
          <p>{phase.purpose}</p>
        </div>
        <Link to={`/projects/${encodeURIComponent(projectId)}`} className="button button--quiet">Project overview</Link>
      </header>

      {isMethodSelectionPhase ? (
        <Panel
          eyebrow="Current Phase 2 catalog"
          title="Select the exact method for this run"
          description={`Selection does not start ${phaseId}. It resolves the method-specific record and run command.`}
        >
          {methodsQuery.isLoading ? <LoadingState label="Loading current methods…" /> : null}
          {methodsQuery.error ? <ErrorState error={methodsQuery.error} title="Methods are unavailable" /> : null}
          {!methodsQuery.isLoading && !methodsQuery.error ? (
            <>
              <MethodSelector methods={methods} selectedMethodId={selectedMethodId} onChange={setSelectedMethodId} />
              {selectedMethod ? <SelectedMethodSummary method={selectedMethod} /> : null}
            </>
          ) : null}
        </Panel>
      ) : null}

      {phaseId === "P2" ? (
        <Panel
          eyebrow="Formal method state"
          title="Feasible method catalog"
          description="Retirement changes lifecycle state only when the backend exposes that controlled action. It does not delete prior records."
        >
          {methodsQuery.isLoading ? <LoadingState label="Loading method catalog…" /> : null}
          {methodsQuery.error ? <ErrorState error={methodsQuery.error} title="Method catalog is unavailable" /> : null}
          {methods.length ? <MethodTable projectId={projectId} methods={methods} /> : null}
          {!methodsQuery.isLoading && !methodsQuery.error && methods.length === 0 ? (
            <EmptyState title="No method has been proposed yet">
              <p>Configure and start the first Phase 2 run below. This table will update after a valid result is published.</p>
            </EmptyState>
          ) : null}
        </Panel>
      ) : null}

      <Panel
        eyebrow="Current formal record"
        title={phase.current_record?.title ?? `Current ${phaseId} result`}
        description="This is the result currently used by the project. A newer attempt replaces it only after successful validation and publication."
      >
        {phase.current_record ? (
          <div className="current-record">
            <p className="current-record__summary">{phase.current_record.summary}</p>
            <ScientificStatusGrid status={phase.current_record.status} />
            <dl className="record-metadata">
              <div><dt>Scientific basis</dt><dd>{phase.current_record.basis_summary}</dd></div>
              <div><dt>Material change</dt><dd>{phase.current_record.change_summary}</dd></div>
              <div><dt>Published</dt><dd>{formatDate(phase.current_record.published_at)}</dd></div>
              {phase.current_record.method_identity ? (
                <div>
                  <dt>Exact method</dt>
                  <dd><code>{phase.current_record.method_identity.stable_id}</code>, v{phase.current_record.method_identity.version}<br />
                    definition <code title={phase.current_record.method_identity.definition_sha256}>{shortDigest(phase.current_record.method_identity.definition_sha256)}</code>
                  </dd>
                </div>
              ) : null}
              <div><dt>Source run</dt><dd><Link to={`/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(phase.current_record.source_run_id)}`}>{phase.current_record.source_run_id}</Link></dd></div>
            </dl>
          </div>
        ) : (
          <EmptyState title="No current formal result">
            <p>{phase.empty_state_message ?? "A result will appear after a user-started run validates and publishes."}</p>
          </EmptyState>
        )}
      </Panel>

      <div className="phase-information-grid">
        <Panel title="Current phase assessment" eyebrow="Separate status dimensions">
          <ScientificStatusGrid status={phase.assessment} />
        </Panel>
        <Panel title="Research artifacts" eyebrow="Evidence and records">
          {phase.artifacts.length ? (
            <ul className="artifact-list">
              {phase.artifacts.map((artifact) => (
                <li key={artifact.artifact_id}>
                  <a href={artifact.href}>{artifact.label}</a>
                  <span>{artifact.information_layer} information{artifact.media_type ? ` · ${artifact.media_type}` : ""}</span>
                </li>
              ))}
            </ul>
          ) : <p className="muted-text">No formal artifact is linked to this view.</p>}
        </Panel>
      </div>

      {phase.decision_brief ? (
        <Panel title={phase.decision_brief.headline} eyebrow="Lead summary for researcher judgment">
          <DecisionBrief brief={phase.decision_brief} />
        </Panel>
      ) : null}

      {phase.evidence.length ? (
        <Panel title="Evidence assessment" eyebrow="Current scientific interpretation">
          <ul className="evidence-list">
            {phase.evidence.map((evidence) => (
              <li key={evidence.evidence_id}>
                <div><strong>{evidence.label}</strong>{evidence.eligibility ? <span>{evidence.eligibility.replaceAll("_", " ")}</span> : null}</div>
                <p>{evidence.assessment}</p>
                {evidence.method_match ? <small>Method match: {evidence.method_match}</small> : null}
                {evidence.href ? <a href={evidence.href}>Open evidence</a> : null}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <div className="phase-information-grid">
        <Panel title="Runs in progress" eyebrow="Active execution">
          <RunList projectId={projectId} runs={phase.active_runs} emptyMessage={`No ${phaseId} run is active.`} />
        </Panel>
        <Panel
          title="Recent runs"
          eyebrow="Attempts and formal result"
          description="The latest attempt and the source of the current formal result are marked separately. A failed, rejected, conflicted, or cancelled attempt does not replace the formal result."
        >
          <RunList
            projectId={projectId}
            runs={phase.recent_runs}
            emptyMessage={`No ${phaseId} run has been recorded.`}
            formalSourceRunId={phase.current_record?.source_run_id ?? null}
            markLatestAttempt
          />
        </Panel>
      </div>

      <Panel
        id="configure-run"
        className="launch-panel"
        eyebrow="User-controlled operation"
        title={`Configure a ${phaseId} run or rerun`}
        description="Choose the scope and context, state your instructions, then review the exact command before launch."
      >
        {!mode ? <LoadingState label="Resolving the default run scope…" /> : (
          <RunForm
            key={`${projectId}-${phaseId}-run-form`}
            projectId={projectId}
            phaseView={phase}
            methods={methods}
            selectedMethodId={selectedMethodId}
            onMethodChange={setSelectedMethodId}
            mode={mode}
            onModeChange={(nextMode) => {
              setMode(nextMode);
              if (phaseId === "P2" && nextMode !== "p2.focused_method") setSelectedMethodId("");
            }}
          />
        )}
      </Panel>

      <ProjectionNote projection={phase.projection} />
    </div>
  );
}
