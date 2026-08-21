// @vitest-environment jsdom
/**
 * Phase-tab redesign (2026-08-21, Tez-approved mock): render-rule coverage.
 *
 * 1. CompactPhaseStatus outcome-text dedupe: the outcome words render only
 *    when they add information beyond the pills (an assessed outcome), never
 *    for not_assessed / not_applicable / missing outcomes.
 * 2. PhaseStatusCard clamped decision paragraph: the More/Less expander
 *    appears only when the text overflows the 3-line clamp, and toggles the
 *    clamp. (jsdom has no layout, so overflow is simulated via defined
 *    scrollHeight/clientHeight getters.)
 * 3. MethodCategorySummary: one clamped line per populated category
 *    (Novel / Risk / Assumes, first list item only), falling back to the
 *    clamped summary when no category content exists.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import type { MethodRow, PhaseView, ScientificStatus } from "../api/types";
import { CompactPhaseStatus } from "./Status";
import { PhaseStatusCard } from "./PhaseStatusCard";
import { MethodCategorySummary } from "./MethodTable";

afterEach(() => {
  cleanup();
});

function status(overrides: Partial<ScientificStatus> = {}): ScientificStatus {
  return {
    record_position: "current",
    alignment: "exact",
    attention: "none",
    ...overrides,
  };
}

describe("CompactPhaseStatus outcome dedupe", () => {
  it("keeps an assessed outcome as text next to the pill", () => {
    render(<CompactPhaseStatus status={status({ scientific_outcome: "supported" })} />);
    expect(screen.getByText("Current")).toBeInTheDocument();
    expect(screen.getByText("Supported under stated assumptions")).toBeInTheDocument();
  });

  it("hides the outcome text when the outcome is not assessed", () => {
    const { container } = render(
      <CompactPhaseStatus status={status({ alignment: "unassessed", scientific_outcome: "not_assessed" })} />,
    );
    expect(screen.getByText("Unassessed")).toBeInTheDocument();
    expect(container.querySelector(".compact-phase-status__outcome")).toBeNull();
    expect(screen.queryByText(/not assessed/i)).not.toBeInTheDocument();
  });

  it("hides the outcome text when the outcome is not applicable", () => {
    const { container } = render(
      <CompactPhaseStatus status={status({ scientific_outcome: "not_applicable" })} />,
    );
    expect(container.querySelector(".compact-phase-status__outcome")).toBeNull();
  });

  it("hides the outcome text when no status exists at all", () => {
    const { container } = render(<CompactPhaseStatus status={undefined} />);
    expect(screen.getByText("Not run")).toBeInTheDocument();
    expect(container.querySelector(".compact-phase-status__outcome")).toBeNull();
  });

  it("keeps the aria-label free of the outcome when the text is hidden", () => {
    const { container } = render(
      <CompactPhaseStatus status={status({ alignment: "unassessed", scientific_outcome: "not_assessed" })} />,
    );
    const el = container.querySelector(".compact-phase-status");
    expect(el?.getAttribute("aria-label") ?? "").not.toContain("Scientific outcome");
  });
});

function phaseView(overrides: Partial<PhaseView> = {}): PhaseView {
  return {
    phase_id: "P2",
    name: "Method development",
    purpose: "Maintain the method catalog.",
    assessment: status({ scientific_outcome: "not_assessed" }),
    evidence: [],
    artifacts: [],
    run_configuration: {
      modes: [],
      instruction_label: "Instructions",
      instruction_help: "help",
      current_inputs: [],
      history_options: [],
      stage_plan: [],
    },
    actions: [],
    active_runs: [],
    recent_runs: [],
    descriptor_basis: {
      basis_id: "basis-1",
      sealed_at: "2026-08-21T00:00:00Z",
      source: "test",
    },
    projection: {},
    decision_brief: {
      current_decision: "A long assessment paragraph that may or may not overflow the clamp.",
      items: [],
      actions: [],
    },
    ...overrides,
  } as unknown as PhaseView;
}

describe("PhaseStatusCard clamped decision text", () => {
  it("renders the label and paragraph without an expander when nothing overflows", () => {
    render(<PhaseStatusCard phase={phaseView()} />);
    expect(screen.getByText("Latest assessment")).toBeInTheDocument();
    expect(screen.getByText(/long assessment paragraph/)).toBeInTheDocument();
    // jsdom has no layout: scrollHeight == clientHeight == 0, no overflow.
    expect(screen.queryByRole("button", { name: "More" })).not.toBeInTheDocument();
  });

  it("shows the expander on overflow and toggles the clamp", async () => {
    const scrollHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollHeight");
    const clientHeight = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "clientHeight");
    Object.defineProperty(HTMLElement.prototype, "scrollHeight", { configurable: true, get() { return 120; } });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get() { return 48; } });
    try {
      render(<PhaseStatusCard phase={phaseView()} />);
      const more = await screen.findByRole("button", { name: "More" });
      const paragraph = screen.getByText(/long assessment paragraph/);
      expect(paragraph).toHaveAttribute("data-clamped", "");
      await userEvent.click(more);
      expect(paragraph).not.toHaveAttribute("data-clamped");
      expect(screen.getByRole("button", { name: "Less" })).toHaveAttribute("aria-expanded", "true");
    } finally {
      if (scrollHeight) Object.defineProperty(HTMLElement.prototype, "scrollHeight", scrollHeight);
      if (clientHeight) Object.defineProperty(HTMLElement.prototype, "clientHeight", clientHeight);
    }
  });
});

function methodRow(overrides: Partial<MethodRow> = {}): MethodRow {
  return {
    identity: { stable_id: "method.example", version: 1, definition_sha256: "abc123" },
    display_name: "Example Method",
    lifecycle_state: "active",
    summary: "The plain summary paragraph used as the fallback.",
    mathematical_summary: "x_{t+1} = x_t + h b(x_t) + sqrt(2h) xi_t",
    phase_statuses: {},
    ...overrides,
  } as MethodRow;
}

describe("MethodCategorySummary", () => {
  it("renders one line per populated category, first list item only", () => {
    const { container } = render(
      <MethodCategorySummary
        method={methodRow({
          novelty_summary: "First catalog candidate with noise-channel coupling.",
          principal_risks: ["The main risk.", "A secondary risk."],
          assumptions: ["Exact product invariance.", "Constant step size."],
        })}
      />,
    );
    const lines = Array.from(container.querySelectorAll(".method-table__category"));
    expect(lines).toHaveLength(3);
    const [novel, risk, assumes] = lines as [Element, Element, Element];
    expect(novel.textContent).toContain("Novel:");
    expect(risk.textContent).toContain("Risk:");
    expect(risk.textContent).toContain("The main risk.");
    expect(risk.textContent).not.toContain("A secondary risk.");
    expect(assumes.textContent).toContain("Assumes:");
    expect(assumes.textContent).toContain("Exact product invariance.");
    // The plain summary is not rendered alongside categories.
    expect(screen.queryByText(/plain summary paragraph/)).not.toBeInTheDocument();
  });

  it("renders only the populated categories", () => {
    const { container } = render(
      <MethodCategorySummary method={methodRow({ principal_risks: ["Only risk."] })} />,
    );
    const lines = Array.from(container.querySelectorAll(".method-table__category"));
    expect(lines).toHaveLength(1);
    expect(lines[0]?.textContent).toContain("Risk:");
  });

  it("falls back to the clamped summary when no category content exists", () => {
    const { container } = render(<MethodCategorySummary method={methodRow()} />);
    const fallback = container.querySelector(".method-table__summary--clamped");
    expect(fallback).not.toBeNull();
    expect(fallback?.textContent).toContain("plain summary paragraph");
    expect(container.querySelector(".method-table__category")).toBeNull();
  });
});
