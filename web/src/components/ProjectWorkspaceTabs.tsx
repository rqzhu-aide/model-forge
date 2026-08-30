import { NavLink } from "react-router-dom";
import type { PhaseId, ProjectOverview } from "../api/types";
import { phaseNames, phaseShortNames } from "../utils/format";

const phases: PhaseId[] = ["P1", "P2", "P3", "P4", "P5"];

export type WorkspaceStatusTone = "neutral" | "current" | "running" | "attention";

export interface PhaseWorkspaceStatus {
  label: string;
  detail: string;
  tone: WorkspaceStatusTone;
}

export function getPhaseWorkspaceStatus(
  phase: PhaseId,
  overview: ProjectOverview | undefined,
): PhaseWorkspaceStatus {
  const authoritative = overview?.phases.find((item) => item.phase_id === phase);
  if (!authoritative) {
    return {
      label: "Status unavailable",
      detail: "No authoritative phase summary is available.",
      tone: "neutral",
    };
  }

  const state = {
    no_current_record: { label: "No current record", tone: "neutral" },
    active_run: {
      label: authoritative.active_run_count === 1
        ? "Run in progress"
        : `${authoritative.active_run_count} runs in progress`,
      tone: "running",
    },
    current_records: { label: "Current", tone: "current" },
    attention_required: { label: "Needs attention", tone: "attention" },
  }[authoritative.navigation_state] as {
    label: string;
    tone: WorkspaceStatusTone;
  };

  return {
    ...state,
    detail: authoritative.summary,
  };
}

interface ProjectWorkspaceTabsProps {
  projectId: string;
  overview?: ProjectOverview | undefined;
  loading?: boolean;
}

export function ProjectWorkspaceTabs({ projectId, overview, loading = false }: ProjectWorkspaceTabsProps) {
  const basePath = `/projects/${encodeURIComponent(projectId)}`;

  return (
    <nav className="project-workspace-tabs" aria-label="Project sections">
      <NavLink
        to={basePath}
        end
        className={({ isActive }) => isActive ? "project-workspace-tab is-active" : "project-workspace-tab"}
      >
        <span className="project-workspace-tab__label">Overview</span>
        <small>Project state</small>
      </NavLink>
      {phases.map((phase) => {
        const status = getPhaseWorkspaceStatus(phase, overview);
        return (
          <NavLink
            to={`${basePath}/phases/${phase}`}
            key={phase}
            data-phase={phase}
            className={({ isActive }) => isActive ? "project-workspace-tab is-active" : "project-workspace-tab"}
            title={`${phase}: ${phaseNames[phase]}. ${status.label}.`}
          >
            <span className="project-workspace-tab__label">
              <span
                className="project-workspace-tab__status"
                data-tone={loading ? "neutral" : status.tone}
                aria-hidden="true"
              />
              <span>{phase}</span> {phaseShortNames[phase]}
            </span>
            <small>{loading ? "Loading status" : status.label}</small>
          </NavLink>
        );
      })}
      <NavLink
        to={`${basePath}/supervised`}
        className={({ isActive }) => isActive ? "project-workspace-tab is-active" : "project-workspace-tab"}
      >
        <span className="project-workspace-tab__label">Supervised runs</span>
        <small>Sealed invocations</small>
      </NavLink>
    </nav>
  );
}
