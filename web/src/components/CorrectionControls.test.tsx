// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type {
  ActionDescriptor,
  CorrectionFinding,
  CorrectionPreview,
  CorrectionType,
  RunDetail,
} from "../api/types";
import {
  CORRECTION_ACTION_TYPES,
  CorrectionControls,
  correctionActionsOf,
  correctionStateNotice,
  normalizeCodesFromPreview,
} from "./CorrectionControls";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      previewRunCorrection: vi.fn(),
      requestRunCorrection: vi.fn(),
    },
  };
});

const previewMock = vi.mocked(api.previewRunCorrection);
const correctionMock = vi.mocked(api.requestRunCorrection);
const settledMock = vi.fn<(run: RunDetail) => Promise<void>>().mockResolvedValue(undefined);

function correctionAction(type: CorrectionType, overrides: Partial<ActionDescriptor> = {}): ActionDescriptor {
  return {
    descriptor_id: `action.${type}.1`,
    action_type: CORRECTION_ACTION_TYPES[type],
    execution_kind: "control_transaction",
    enabled: true,
    consequence_summary: `${type} consequence.`,
    run_id: "run-1",
    ...overrides,
  };
}

function runWith(actions: ActionDescriptor[], state: RunDetail["state"] = "failed"): RunDetail {
  return {
    run_id: "run-1",
    phase: "P2",
    mode: "catalog_revision",
    state,
    requested_at: "2026-08-20T00:00:00Z",
    updated_at: "2026-08-20T00:05:00Z",
    actions,
    requested_by: "tez",
    instructions: "Revise the catalog.",
    contract: { phase_contract_version: "1.0.0", phase_contract_sha256: "a".repeat(64) },
    frozen_basis: [],
    stage_plan: [],
    last_event_sequence: 0,
  };
}

function finding(code: string, pointer = ""): CorrectionFinding {
  return {
    code,
    message: `${code} message`,
    severity: "error",
    json_pointer: pointer,
    finding_class: "correctable_contract_error",
    blocks_publication: true,
    correction_class: "mechanical",
  };
}

function preview(overrides: Partial<CorrectionPreview> = {}): CorrectionPreview {
  return {
    current_findings: [finding("schema.required"), finding("schema.type", "/sequence")],
    remaining_findings: [],
    fixed_findings: [finding("schema.required")],
    transformations: [
      {
        contract_output_id: "p1.theory_discovery",
        source_sha256: "a".repeat(64),
        result_sha256: "b".repeat(64),
        entries: [
          { code: "timestamp_injection", json_pointer: "", detail: "created_at stamped" },
          { code: "id_sanitization", json_pointer: "/record_id", detail: "id sanitized" },
        ],
        primary_artifact_unchanged: true,
      },
    ],
    passing: true,
    output_scope: ["p1.theory_discovery"],
    ...overrides,
  };
}

function renderControls(run: RunDetail) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <CorrectionControls projectId="project-1" run={run} onCorrectionSettled={settledMock} />
    </QueryClientProvider>,
  );
}

const allFour = (["revalidate", "normalize", "packaging", "scientific"] as CorrectionType[]).map(
  (type) => correctionAction(type),
);

beforeEach(() => {
  // jsdom does not implement HTMLDialogElement.showModal/close; the dialog
  // only needs the open attribute for its contents to be queryable.
  window.HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  window.HTMLDialogElement.prototype.close = function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
});

afterEach(cleanup);

describe("CorrectionControls rendering", () => {
  it("renders nothing when no correction descriptors are present", () => {
    previewMock.mockReset();
    const { container } = renderControls(
      runWith([
        {
          descriptor_id: "action.cancel.1",
          action_type: "cancel_run",
          enabled: true,
          consequence_summary: "Stop the run.",
        },
      ]),
    );
    expect(container.firstChild).toBeNull();
    expect(previewMock).not.toHaveBeenCalled();
  });

  it("renders every correction action row from the run descriptors", async () => {
    previewMock.mockReset();
    previewMock.mockResolvedValue(preview());
    renderControls(runWith(allFour));
    // Wait for the settled tree: the command buttons render disabled while
    // the dry run is still in flight.
    expect(await screen.findByText(/Dry run clears all blocking checks/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-check sealed outputs" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Apply normalization" })).toBeEnabled();
    expect(screen.getByText("packaging consequence.")).toBeInTheDocument();
    expect(previewMock).toHaveBeenCalledWith("project-1", "run-1");
  });
});

describe("correction commands", () => {
  it("posts a revalidate command scoped by the preview output_scope", async () => {
    previewMock.mockReset();
    correctionMock.mockReset();
    settledMock.mockClear();
    previewMock.mockResolvedValue(preview());
    correctionMock.mockResolvedValue(runWith(allFour, "correcting"));
    const user = userEvent.setup();
    renderControls(runWith(allFour));
    await screen.findByText(/Dry run clears all blocking checks/);

    await user.click(screen.getByRole("button", { name: "Re-check sealed outputs" }));
    await user.click(await screen.findByRole("button", { name: "Confirm re-check" }));

    expect(correctionMock).toHaveBeenCalledTimes(1);
    expect(correctionMock).toHaveBeenCalledWith("project-1", "run-1", allFour[0], {
      correction_type: "revalidate",
      permitted_output_scope: ["p1.theory_discovery"],
    });
    expect(settledMock).toHaveBeenCalledTimes(1);
  });

  it("sends the preview-derived transformation codes on normalize apply", async () => {
    previewMock.mockReset();
    correctionMock.mockReset();
    previewMock.mockResolvedValue(preview());
    correctionMock.mockResolvedValue(runWith(allFour, "correcting"));
    const user = userEvent.setup();
    renderControls(runWith(allFour));
    await screen.findByText(/Dry run clears all blocking checks/);

    await user.click(screen.getByRole("button", { name: "Apply normalization" }));
    await user.click(await screen.findByRole("button", { name: "Confirm normalization" }));

    expect(correctionMock).toHaveBeenCalledWith("project-1", "run-1", allFour[1], {
      correction_type: "normalize",
      permitted_output_scope: ["p1.theory_discovery"],
      transformation_codes: ["id_sanitization", "timestamp_injection"],
    });
  });

  it("keeps normalize disabled when the dry run leaves blocking checks", async () => {
    previewMock.mockReset();
    correctionMock.mockReset();
    previewMock.mockResolvedValue(
      preview({ passing: false, remaining_findings: [finding("schema.type", "/sequence")] }),
    );
    renderControls(runWith(allFour));
    expect(
      await screen.findByText(/does not clear every blocking check/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply normalization" })).toBeDisabled();
    expect(correctionMock).not.toHaveBeenCalled();
  });

  it("requires a revision instruction before a scientific correction", async () => {
    previewMock.mockReset();
    correctionMock.mockReset();
    previewMock.mockResolvedValue(preview());
    correctionMock.mockResolvedValue(runWith(allFour, "correcting"));
    const user = userEvent.setup();
    renderControls(runWith(allFour));
    await screen.findByText(/Dry run clears all blocking checks/);

    const button = screen.getByRole("button", { name: "Request scientific revision" });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText("Revision instruction"), "Tighten the theorem scope.");
    expect(button).toBeEnabled();
    await user.click(button);
    await user.click(await screen.findByRole("button", { name: "Confirm scientific revision" }));

    expect(correctionMock).toHaveBeenCalledWith("project-1", "run-1", allFour[3], {
      correction_type: "scientific",
      permitted_output_scope: ["p1.theory_discovery"],
      user_instruction: "Tighten the theorem scope.",
    });
  });

  it("disables every command when the preview fails", async () => {
    previewMock.mockReset();
    correctionMock.mockReset();
    previewMock.mockRejectedValue(new ApiError("not applicable", 409));
    renderControls(runWith(allFour));
    // The refusal appears both as the preview error state and as the
    // per-button disabled reason (one per action row).
    const reasons = await screen.findAllByText(/the output scope cannot be determined/);
    expect(reasons).toHaveLength(4);
    expect(screen.getByRole("button", { name: "Re-check sealed outputs" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Request packaging correction" })).toBeDisabled();
    expect(correctionMock).not.toHaveBeenCalled();
  });
});

describe("correction helpers", () => {
  it("maps descriptors by correction type", () => {
    const found = correctionActionsOf(runWith(allFour));
    expect(found.revalidate?.descriptor_id).toBe("action.revalidate.1");
    expect(found.packaging?.action_type).toBe("package_run_outputs");
    expect(correctionActionsOf(runWith([]))).toEqual({});
  });

  it("derives sorted distinct normalize codes from the preview", () => {
    const codes = normalizeCodesFromPreview(preview());
    expect(codes).toEqual(["id_sanitization", "timestamp_injection"]);
    expect(normalizeCodesFromPreview(preview({ transformations: [] }))).toEqual([]);
  });

  it("presents correction states distinctly", () => {
    expect(correctionStateNotice(runWith([], "correction_authorized"))?.title).toBe(
      "Correction authorized",
    );
    expect(correctionStateNotice(runWith([], "correcting"))?.className).toBe(
      "message message--neutral",
    );
    const exhausted = correctionStateNotice(runWith([], "correction_exhausted"));
    expect(exhausted?.className).toBe("message message--warning");
    expect(exhausted?.body).toContain("full phase rerun");
    expect(correctionStateNotice(runWith([], "published"))).toBeUndefined();
  });
});
