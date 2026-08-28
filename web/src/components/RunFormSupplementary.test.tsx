// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ActionDescriptor, PhaseView, StartRunRequest } from "../api/types";
import { RunForm } from "./RunForm";

const startRunMock = vi.fn<(projectId: string, input: StartRunRequest) => Promise<unknown>>();

vi.mock("../api/client", () => ({
  api: {
    startRun: (projectId: string, input: StartRunRequest) => startRunMock(projectId, input),
  },
}));

const action: ActionDescriptor = {
  descriptor_id: "descriptor.p1",
  action_type: "start_run",
  execution_kind: "research_run",
  enabled: true,
  consequence_summary: "Run once.",
  command_contract: {
    phase: "P1",
    phase_contract_version: "2.4.0",
    phase_contract_sha256: "a".repeat(64),
    mode: "p1.update",
  },
} as ActionDescriptor;

const phaseView: PhaseView = {
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
    supplementary_inputs: [
      {
        input_id: "p1.researcher_material",
        label: "Supplementary material",
        purpose: "Accept researcher-supplied material such as the researcher's own paper.",
      },
    ],
    stage_plan: [],
  },
  actions: [action],
  active_runs: [],
  recent_runs: [],
  projection: {},
} as unknown as PhaseView;

function renderForm(view: PhaseView = phaseView) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <RunForm
          projectId="project-1"
          phaseView={view}
          methods={[]}
          selectedMethodId=""
          onMethodChange={() => undefined}
          mode="p1.update"
          onModeChange={() => undefined}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function launch(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Review this run" }));
  await user.click(screen.getByRole("button", { name: "Start this run" }));
  await waitFor(() => expect(startRunMock).toHaveBeenCalledTimes(1));
  const call = startRunMock.mock.calls[0];
  if (!call) throw new Error("startRun was not called");
  return call[1];
}

describe("RunForm supplementary material (ADR-019)", () => {
  beforeEach(() => {
    startRunMock.mockReset();
    startRunMock.mockResolvedValue({ run_id: "run.1" });
    window.localStorage.clear();
  });
  afterEach(cleanup);

  it("defaults to none and launches without seed_inputs", async () => {
    const user = userEvent.setup();
    renderForm();
    expect(screen.getByText("Supplementary material")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^None/ })).toBeChecked();
    const payload = await launch(user);
    expect(payload.seed_inputs).toBeUndefined();
  });

  it("hides the fieldset when the contract declares no supplementary slot", () => {
    const without = {
      ...phaseView,
      run_configuration: { ...phaseView.run_configuration, supplementary_inputs: [] },
    } as PhaseView;
    renderForm(without);
    expect(screen.queryByText("Supplementary material")).not.toBeInTheDocument();
  });

  it("copy mode seals pasted content as researcher material", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByRole("radio", { name: /Copy into the project record/ }));
    await user.type(
      screen.getByPlaceholderText(/Paste the material here/),
      "def partial_fit(x): return x",
    );
    const payload = await launch(user);
    expect(payload.seed_inputs).toEqual({
      "p1.researcher_material": {
        content: "def partial_fit(x): return x",
        media_type: "text/markdown",
      },
    });
  });

  it("copy mode with empty content sends no seed", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByRole("radio", { name: /Copy into the project record/ }));
    const payload = await launch(user);
    expect(payload.seed_inputs).toBeUndefined();
  });

  it("link mode seals the URL as an external reference", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByRole("radio", { name: /External link/ }));
    await user.type(
      screen.getByPlaceholderText("https://..."),
      "https://data.example.org/big-archive.tar",
    );
    const payload = await launch(user);
    expect(payload.seed_inputs).toEqual({
      "p1.researcher_material": {
        content: "https://data.example.org/big-archive.tar",
        media_type: "text/uri-list",
      },
    });
  });

  it("blocks launch while the external link is not a valid URL", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByRole("radio", { name: /External link/ }));
    await user.type(screen.getByPlaceholderText("https://..."), "not-a-url");
    expect(screen.getByRole("button", { name: "Review this run" })).toBeDisabled();
    expect(screen.getByText("This does not look like a valid http(s) URL.")).toBeInTheDocument();
  });
});
