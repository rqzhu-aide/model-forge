import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { PhaseView } from "../api/types";
import { PHASE_ONE_SCOPE_OPTIONS, RunForm } from "./RunForm";

const phaseOneView: PhaseView = {
  phase_id: "P1",
  name: "Literature foundation",
  purpose: "Build the literature basis.",
  assessment: {},
  evidence: [],
  artifacts: [],
  run_configuration: {
    modes: [{ mode_id: "p1.update", label: "Update literature", description: "Run Phase 1." }],
    default_mode: "p1.update",
    instruction_label: "Scientific instructions",
    instruction_help: "State the question and evidence boundary.",
    current_inputs: [],
    history_options: [],
    stage_plan: [],
  },
  actions: [],
  active_runs: [],
  recent_runs: [],
  projection: {},
};

describe("Phase 1 run scope", () => {
  it("offers only the two contract enum values and defaults to a broad update", () => {
    expect(PHASE_ONE_SCOPE_OPTIONS.map((option) => option.value)).toEqual([
      "broad_update",
      "focused_update",
    ]);

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RunForm
            projectId="project-1"
            phaseView={phaseOneView}
            methods={[]}
            selectedMethodId=""
            onMethodChange={() => undefined}
            mode="p1.update"
            onModeChange={() => undefined}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(markup).toContain('name="phase-one-scope"');
    expect(markup).toMatch(/name="phase-one-scope" checked="" value="broad_update"/);
    expect(markup).toContain('value="focused_update"');
    expect(markup).not.toContain("Literature search scope</span><textarea");
    expect(markup).toContain("State the scientific boundary in the instructions below.");
  });
});
