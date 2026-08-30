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
const listMaterialsMock = vi.fn<(projectId: string) => Promise<unknown>>();
const getMaterialContentMock =
  vi.fn<(projectId: string, materialId: string) => Promise<unknown>>();

vi.mock("../api/client", () => ({
  api: {
    startRun: (projectId: string, input: StartRunRequest) => startRunMock(projectId, input),
    listMaterials: (projectId: string) => listMaterialsMock(projectId),
    getMaterialContent: (projectId: string, materialId: string) =>
      getMaterialContentMock(projectId, materialId),
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
    listMaterialsMock.mockReset();
    listMaterialsMock.mockResolvedValue([]);
    getMaterialContentMock.mockReset();
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

  it("offers shelf material and seals the stored payload", async () => {
    listMaterialsMock.mockResolvedValue([
      {
        material_id: "material.abc",
        name: "partial_fit.py",
        kind: "copy",
        media_type: "text/plain",
        size_bytes: 30,
        created_at: "2026-08-28T10:00:00Z",
      },
    ]);
    getMaterialContentMock.mockResolvedValue({
      material_id: "material.abc",
      content: "def partial_fit(x): return x",
      media_type: "text/plain",
    });
    const user = userEvent.setup();
    renderForm();
    await user.click(
      await screen.findByRole("radio", { name: /From the project shelf/ }),
    );
    // Launch is blocked until a shelf item is chosen.
    expect(screen.getByRole("button", { name: "Review this run" })).toBeDisabled();
    await user.selectOptions(screen.getByRole("combobox"), "material.abc");
    const payload = await launch(user);
    expect(getMaterialContentMock).toHaveBeenCalledWith("project-1", "material.abc");
    expect(payload.seed_inputs).toEqual({
      "p1.researcher_material": {
        content: "def partial_fit(x): return x",
        media_type: "text/plain",
      },
    });
  });

  it("hides the shelf option when the shelf is empty", () => {
    renderForm();
    expect(screen.queryByRole("radio", { name: /From the project shelf/ })).not.toBeInTheDocument();
  });
});


describe("RunForm one-click rerun prefill (WP-UX)", () => {
  beforeEach(() => {
    startRunMock.mockReset();
    startRunMock.mockResolvedValue({ run_id: "run.1" });
    listMaterialsMock.mockReset();
    listMaterialsMock.mockResolvedValue([]);
    getMaterialContentMock.mockReset();
    window.localStorage.clear();
  });
  afterEach(cleanup);

  it("pre-fills instructions and scope from the frozen basis and shows the note", async () => {
    const rerunPrefill = {
      phase: "P1" as const,
      mode: "p1.update",
      choice_values: {
        "p1.instructions": "Replicate the earlier sweep exactly.",
        "p1.scope": "focused_update",
      },
      context_policy: "current_only",
    };
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RunForm
            projectId="project-1"
            phaseView={phaseView}
            methods={[]}
            selectedMethodId=""
            onMethodChange={() => undefined}
            mode="p1.update"
            onModeChange={() => undefined}
            rerunPrefill={rerunPrefill}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(
        screen.getByText(/Pre-filled from the finished run's frozen basis/),
      ).toBeInTheDocument(),
    );
    const textarea = screen.getByRole("textbox", { name: /instructions/i });
    await waitFor(() => expect(textarea).toHaveValue("Replicate the earlier sweep exactly."));
    expect(screen.getByRole("radio", { name: /Focused literature question/i })).toBeChecked();
  });
  it("applies the method prefill when the method list arrives late and leaves the local draft untouched (B2, B7)", async () => {
    const p4View: PhaseView = {
      ...phaseView,
      phase_id: "P4",
      run_configuration: {
        ...phaseView.run_configuration,
        modes: [
          {
            mode_id: "p4.preliminary",
            label: "Preliminary",
            description: "Preliminary empirical evaluation.",
          },
        ],
        default_mode: "p4.preliminary",
      },
    };
    const methodRow = {
      identity: {
        stable_id: "method.anel",
        version: 1,
        definition_sha256: "a".repeat(64),
      },
      lifecycle_state: "active",
    };
    const rerunPrefill = {
      phase: "P4" as const,
      mode: "p4.preliminary",
      choice_values: {
        "p4.instructions": "Re-run the preliminary evaluation.",
        "p4.selected_method": methodRow.identity,
      },
      context_policy: "current_only",
    };
    // The user's own unsent draft must survive the prefill (B7).
    const draftKey = "model-forge:run-instructions:v1:project-1:P4";
    window.localStorage.setItem(draftKey, "my own draft notes");
    const onMethodChange = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const element = (methods: unknown[]) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <RunForm
            projectId="project-1"
            phaseView={p4View}
            methods={methods as never}
            selectedMethodId=""
            onMethodChange={onMethodChange}
            mode="p4.preliminary"
            onModeChange={() => undefined}
            rerunPrefill={rerunPrefill}
          />
        </MemoryRouter>
      </QueryClientProvider>
    );

    const { rerender } = render(element([]));
    // Methods not yet loaded: nothing applied yet.
    expect(onMethodChange).not.toHaveBeenCalled();
    // Methods arrive (the query resolves): the prefill retries and applies.
    rerender(element([methodRow]));
    await waitFor(() => expect(onMethodChange).toHaveBeenCalledWith("method.anel"));
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: /instructions/i })).toHaveValue(
        "Re-run the preliminary evaluation.",
      ),
    );
    expect(window.localStorage.getItem(draftKey)).toBe("my own draft notes");
    expect(
      screen.getByText(/your local draft is untouched/i),
    ).toBeInTheDocument();
  });
});
