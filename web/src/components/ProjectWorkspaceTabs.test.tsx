import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { PhaseNavigationSummary, ProjectOverview } from "../api/types";
import { projectIdFromPathname } from "./AppShell";
import { getPhaseWorkspaceStatus, ProjectWorkspaceTabs } from "./ProjectWorkspaceTabs";

const phaseStates: PhaseNavigationSummary[] = [
  ["P1", "Literature basis", "current_records", "The literature basis is current."],
  ["P2", "Method catalog", "current_records", "Two feasible methods are current."],
  ["P3", "Theory development", "attention_required", "A proof requires reassessment."],
  ["P4", "Empirical evaluation", "active_run", "An empirical run is active."],
  ["P5", "Manuscript assembly", "no_current_record", "No manuscript record exists."],
].map(([phase_id, name, navigation_state, summary]) => ({
  phase_id,
  name,
  navigation_state,
  formal_record_count: navigation_state === "no_current_record" ? 0 : 1,
  method_scoped_record_count: phase_id === "P3" || phase_id === "P4" ? 1 : 0,
  active_run_count: navigation_state === "active_run" ? 1 : 0,
  assessment: {},
  summary,
})) as PhaseNavigationSummary[];

const overview: ProjectOverview = {
  project: {
    project_id: "project-1",
    name: "Semiparametric study",
    research_question: "Can the estimator remain stable?",
    domains: ["statistics"],
    active_run_count: 1,
  },
  project_brief: {
    project_id: "project-1",
    record_id: "brief-1",
    generation_id: "generation-1",
    research_question: "Can the estimator remain stable?",
    domains: ["statistics"],
    intended_use: "Methods paper",
    decision_criteria: [],
    constraints: [],
    scope_note: "Formal project scope.",
    published_at: "2026-08-02T12:00:00Z",
    artifact: {
      artifact_id: "brief-artifact",
      label: "Project brief",
      information_layer: "primary",
      href: "/brief",
    },
    actions: [],
    projection: {},
  },
  methods: [],
  phases: phaseStates,
  active_runs: [],
  attention_items: [],
  storage: {
    storage_kind: "backend_managed",
    open_folder_supported: false,
    explanation: "Managed by the backend.",
  },
  actions: [],
  projection: {},
};

describe("project workspace navigation", () => {
  it("uses authoritative phase navigation state and summary", () => {
    expect(getPhaseWorkspaceStatus("P3", overview)).toEqual({
      label: "Needs attention",
      detail: "A proof requires reassessment.",
      tone: "attention",
    });
    expect(getPhaseWorkspaceStatus("P4", overview).label).toBe("Run in progress");
  });

  it("renders Overview and all five phases as horizontal project sections", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/projects/project-1/phases/P3"]}>
        <ProjectWorkspaceTabs projectId="project-1" overview={overview} />
      </MemoryRouter>,
    );

    expect(markup).toContain('aria-label="Project sections"');
    expect(markup).toContain("Overview");
    expect(markup).toContain("P1");
    expect(markup).toContain("P5");
    expect(markup).toContain("Needs attention");
    expect(markup.match(/project-workspace-tab/g)?.length).toBeGreaterThanOrEqual(6);
  });

  it("resolves project context from child routes in the pathless application shell", () => {
    expect(projectIdFromPathname("/projects/project-1")).toBe("project-1");
    expect(projectIdFromPathname("/projects/project-1/phases/P3")).toBe("project-1");
    expect(projectIdFromPathname("/projects/project-1/runs/run-2")).toBe("project-1");
    expect(projectIdFromPathname("/projects/project-1/settings/profiles")).toBe("project-1");
    expect(projectIdFromPathname("/projects/new")).toBeUndefined();
    expect(projectIdFromPathname("/settings")).toBeUndefined();
  });
});
