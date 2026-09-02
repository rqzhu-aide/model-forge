import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { PhaseId, PhaseView } from "../api/types";
import { DecisionBrief } from "../components/DecisionBrief";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { MethodSelector, SelectedMethodSummary } from "../components/MethodSelector";
import { MethodTable } from "../components/MethodTable";
import { Panel } from "../components/Panel";
import { PhaseStatusCard } from "../components/PhaseStatusCard";
import { ProjectionNote } from "../components/ProjectionNote";
import { ReviewedBasisPanel } from "../components/ReviewedBasisPanel";
import { RunForm } from "../components/RunForm";
import { RunList } from "../components/RunList";
import { formatDate } from "../utils/format";
import { NotFoundPage } from "./NotFoundPage";

const validPhases: PhaseId[] = ["P1", "P2", "P3", "P4", "P5"];

function isPhaseId(value: string | undefined): value is PhaseId {
  return validPhases.includes(value as PhaseId);
}

export function PhasePage() {
  const { projectId, phaseId: rawPhaseId } = useParams();
  const phaseId = isPhaseId(rawPhaseId) ? rawPhaseId : undefined;
  const [mode, setMode] = useState("");
  const [searchParams] = useSearchParams();
  // Deep link from the P2 catalog: ?method=<stable_id> pre-selects the method.
  const [selectedMethodId, setSelectedMethodId] = useState(
    () => searchParams.get("method") ?? "",
  );

  useEffect(() => {
    setMode("");
    // Reset on phase/project change, but honor the deep-link ?method=
    // pre-selection from the P2 catalog.
    setSelectedMethodId(searchParams.get("method") ?? "");
  }, [phaseId, projectId, searchParams]);

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
    // F2: a mode/method switch changes the query key; keep rendering the
    // previous view (with a busy hint) instead of unmounting the run form
    // and wiping its unpersisted local state.
    placeholderData: keepPreviousData,
  });

  // One-click rerun: ?rerun=<run_id> pre-fills the form with the frozen
  // basis of a finished run (WP-UX).
  const rerunRunId = searchParams.get("rerun") ?? "";
  const rerunQuery = useQuery({
    queryKey: ["run", projectId, rerunRunId],
    queryFn: () => api.getRun(projectId as string, rerunRunId),
    enabled: Boolean(projectId && rerunRunId),
  });
  const rerunPrefill = rerunQuery.data?.rerun_prefill;
  // True once the user explicitly picks a mode; rerun prefill then no longer
  // overrides the mode (B1: the frozen basis must win over the default until
  // the user says otherwise).
  const [userModeOverride, setUserModeOverride] = useState(false);

  const availableModes = phaseQuery.data?.run_configuration.modes ?? [];
  const rerunModeApplicable = Boolean(
    rerunPrefill
    && rerunPrefill.phase === phaseId
    && availableModes.some((item) => item.mode_id === rerunPrefill.mode),
  );

  useEffect(() => {
    if (!rerunPrefill || !rerunModeApplicable || userModeOverride) return;
    if (mode !== rerunPrefill.mode) setMode(rerunPrefill.mode);
  }, [rerunPrefill, rerunModeApplicable, userModeOverride, mode]);

  const needsMethods = phaseId === "P2" || phaseId === "P3" || phaseId === "P4" || phaseId === "P5";
  const methodsQuery = useQuery({
    queryKey: ["methods", projectId],
    queryFn: () => api.listMethods(projectId as string),
    enabled: Boolean(projectId && needsMethods),
  });

  useEffect(() => {
    const defaultMode = phaseQuery.data?.run_configuration.default_mode;
    if (mode || !defaultMode) return;
    // A pending rerun prefill decides the mode; wait for it (B1).
    if (rerunQuery.isLoading || rerunModeApplicable) return;
    setMode(defaultMode);
  }, [mode, phaseQuery.data?.run_configuration.default_mode, rerunQuery.isLoading, rerunModeApplicable]);

  if (!projectId || !phaseId) return <NotFoundPage />;
  if (phaseQuery.isLoading) return <LoadingState label={`Loading ${phaseId} state…`} />;
  if (phaseQuery.error) return <ErrorState error={phaseQuery.error} title={`${phaseId} state is unavailable`} />;
  if (!phaseQuery.data) return <NotFoundPage />;

  const phase = phaseQuery.data;
  const methods = methodsQuery.data ?? [];
  const selectedMethod = methods.find((method) => method.identity.stable_id === selectedMethodId);
  const isMethodSelectionPhase = phaseId === "P3" || phaseId === "P4";
  const hasResearchDetails = Boolean(
    phase.current_record
    || phase.evidence.length
    || phase.artifacts.length
    || phase.recent_runs.length
    || phase.decision_brief,
  );

  return (
    <div className="page-stack">
      <header className="page-header phase-heading">
        <div>
          <p className="eyebrow" data-phase={phaseId}>{phaseId} research phase</p>
          <h1>{phase.name}</h1>
          <p>{phase.purpose}</p>
        </div>
        <Link to={`/projects/${encodeURIComponent(projectId)}`} className="button button--quiet">Project overview</Link>
      </header>

      {/* ── Tier 1: Compact status ── */}
      <PhaseStatusCard phase={phase} />

      {/* ── Literature gap recommendation (P1 only) ── */}
      {phaseId === "P1" && phase.literature_gaps && phase.literature_gaps.length > 0 ? (
        <div className="literature-gap-banner">
          <p className="literature-gap-banner__heading">
            {phase.literature_gaps.length} suggested reference{phase.literature_gaps.length === 1 ? "" : "s"} from downstream phases
          </p>
          <p className="literature-gap-banner__hint">
            Consider a focused literature update to incorporate these:
          </p>
          <ul className="literature-gap-banner__list">
            {(phase.literature_gaps.length > 2
              ? phase.literature_gaps.slice(0, 2)
              : phase.literature_gaps
            ).map((gap) => (
              <li key={gap.attention_id}>
                <span className="literature-gap-banner__phase">{gap.raised_by_phase}</span>
                {" "}
                <span className="literature-gap-banner__reference">{gap.reference}</span>
              </li>
            ))}
          </ul>
          {phase.literature_gaps.length > 2 ? (
            <details className="literature-gap-banner__more">
              <summary>Show all {phase.literature_gaps.length} suggested references</summary>
              <ul className="literature-gap-banner__list">
                {phase.literature_gaps.slice(2).map((gap) => (
                  <li key={gap.attention_id}>
                    <span className="literature-gap-banner__phase">{gap.raised_by_phase}</span>
                    {" "}
                    <span className="literature-gap-banner__reference">{gap.reference}</span>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}

      {/* ── Tier 2: Configure next run ── */}
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

      {phaseQuery.isFetching ? (
        <p className="phase-view__refresh-note" role="status" aria-live="polite">
          Refreshing the view for the new selection; your entries below are preserved.
        </p>
      ) : null}
      <Panel
        id="configure-run"
        className="launch-panel"
        eyebrow="User-controlled operation"
        title={`Configure a ${phaseId} run or rerun`}
        description="Choose the scope and context, state your instructions, then review the exact command before launch."
      >
        {rerunRunId && rerunQuery.error ? (
          <ErrorState
            error={rerunQuery.error}
            title="The source run for the rerun could not be loaded"
          />
        ) : null}
        {rerunRunId && rerunQuery.isSuccess && !rerunPrefill ? (
          <p className="run-form__rerun-note" role="status">
            That run does not offer a rerun basis; the form below starts fresh.
          </p>
        ) : null}
        {!mode ? <LoadingState label="Resolving the default run scope…" /> : (
          <RunForm
            key={`${projectId}-${phaseId}-run-form`}
            projectId={projectId}
            phaseView={phase}
            methods={methods}
            selectedMethodId={selectedMethodId}
            onMethodChange={setSelectedMethodId}
            mode={mode}
            // Do not hand the rerun prefill to the form while it renders
            // placeholder (previous-key) data: RunForm's apply effect keys
            // on `mode` and would stamp from the stale view's history
            // options, then skip the correct re-stamp once fresh data
            // lands. Withholding it during the placeholder window resets
            // RunForm's applied-marker, so the stamp runs once, against the
            // real view.
            rerunPrefill={
              !phaseQuery.isPlaceholderData && rerunPrefill?.phase === phaseId
                ? rerunPrefill
                : undefined
            }
            onModeChange={(nextMode) => {
              setUserModeOverride(true);
              setMode(nextMode);
              if (phaseId === "P2" && nextMode !== "p2.focused_method") setSelectedMethodId("");
            }}
          />
        )}
      </Panel>

      {/* ── Tier 3: Research details (collapsed by default) ── */}
      {hasResearchDetails ? (
        <details className="phase-research-details">
          <summary>Research details and decision context</summary>
          <div className="phase-research-details__body">
            {phase.decision_brief ? (
              <Panel title={phase.decision_brief.headline} eyebrow="Lead summary for researcher judgment">
                <DecisionBrief brief={phase.decision_brief} />
              </Panel>
            ) : null}

            {phase.current_record ? (
              <Panel title={phase.current_record.title} eyebrow="Current formal record">
                <p className="current-record__summary">{phase.current_record.summary}</p>
                <dl className="record-metadata">
                  <div><dt>Scientific basis</dt><dd>{phase.current_record.basis_summary}</dd></div>
                  <div><dt>Material change</dt><dd>{phase.current_record.change_summary}</dd></div>
                  <div><dt>Published</dt><dd>{formatDate(phase.current_record.published_at)}</dd></div>
                  <div>
                    <dt>Source run</dt>
                    <dd>
                      <Link to={`/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(phase.current_record.source_run_id)}`}>
                        {phase.current_record.source_run_id}
                      </Link>
                    </dd>
                  </div>
                </dl>
              </Panel>
            ) : null}

            {phase.evidence.length ? (
              <Panel title="Evidence assessment" eyebrow="Current scientific interpretation">
                <ul className="evidence-list">
                  {phase.evidence.map((evidence) => (
                    <li key={evidence.evidence_id}>
                      <div>
                        <strong>{evidence.label}</strong>
                        {evidence.eligibility ? <span>{evidence.eligibility.replaceAll("_", " ")}</span> : null}
                      </div>
                      <p>{evidence.assessment}</p>
                      {evidence.method_match ? <small>Method match: {evidence.method_match}</small> : null}
                      {evidence.href ? <a href={evidence.href}>Open evidence</a> : null}
                    </li>
                  ))}
                </ul>
              </Panel>
            ) : null}

            {phase.artifacts.length ? (
              <Panel title="Research artifacts" eyebrow="Evidence and records">
                <ul className="artifact-list">
                  {phase.artifacts.map((artifact, index) => (
                    /* The same artifact can repeat per information layer and
                       across records, so the key needs the list position. */
                    <li key={`${artifact.artifact_id}:${artifact.information_layer}:${index}`}>
                      <a href={artifact.href}>{artifact.label}</a>
                      <span>{artifact.information_layer} information{artifact.media_type ? ` · ${artifact.media_type}` : ""}</span>
                    </li>
                  ))}
                </ul>
              </Panel>
            ) : null}

            <Panel title="Recent runs" eyebrow="Attempts and formal result">
              <RunList
                projectId={projectId}
                runs={phase.recent_runs}
                emptyMessage={`No ${phaseId} run has been recorded.`}
                formalSourceRunId={phase.current_record?.source_run_id ?? null}
                markLatestAttempt
              />
            </Panel>
          </div>
        </details>
      ) : null}

      {/* ── Audit & provenance (collapsed, system-level) ── */}
      <details className="phase-audit-details">
        <summary>Audit and provenance</summary>
        <div className="phase-audit-details__body">
          {phase.current_record ? (
            <Panel title="Full record metadata" eyebrow="System provenance">
              <dl className="record-metadata">
                <div><dt>Record ID</dt><dd><code>{phase.current_record.record_id}</code></dd></div>
                <div><dt>Generation ID</dt><dd><code>{phase.current_record.generation_id}</code></dd></div>
                {phase.current_record.method_identity ? (
                  <div>
                    <dt>Exact method</dt>
                    <dd>
                      <code>{phase.current_record.method_identity.stable_id}</code>, v{phase.current_record.method_identity.version}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </Panel>
          ) : null}

          {phase.active_runs.length ? (
            <Panel title="Runs in progress" eyebrow="Active execution">
              <RunList projectId={projectId} runs={phase.active_runs} emptyMessage={`No ${phaseId} run is active.`} />
            </Panel>
          ) : null}

          <ReviewedBasisPanel basis={phase.descriptor_basis} />

          <ProjectionNote projection={phase.projection} />
        </div>
      </details>
    </div>
  );
}
