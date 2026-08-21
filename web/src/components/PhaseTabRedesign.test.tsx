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
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import type { MethodEvaluation, MethodRow, PhaseView, ScientificStatus } from "../api/types";
import { CompactPhaseStatus } from "./Status";
import { PhaseStatusCard } from "./PhaseStatusCard";
import { MethodCategorySummary, MethodTable } from "./MethodTable";
import { MethodScores, scoreTone } from "./MethodScores";
import { MethodSelector } from "./MethodSelector";

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

function evaluation(overrides: Partial<MethodEvaluation> = {}): MethodEvaluation {
  return {
    theoretical_validity: {
      score: 8,
      justification: "Identifiable under the stated invariance.",
      issue_refs: ["issue-1", "issue-2"],
    },
    literature_positioning: {
      score: 7,
      justification: "Novel coupling, adjacent to prior work.",
      issue_refs: [],
    },
    empirical_feasibility: {
      score: 4,
      justification: "Compute budget exceeds the pilot scale.",
      issue_refs: ["issue-3"],
    },
    adjudicated_at: "2026-08-21T12:00:00Z",
    review_basis_ids: ["review-1"],
    ...overrides,
  };
}

describe("scoreTone", () => {
  it("bands scores 8+ as ok, 5-7 as warn, 1-4 as danger", () => {
    expect(scoreTone(10)).toBe("ok");
    expect(scoreTone(8)).toBe("ok");
    expect(scoreTone(7)).toBe("warn");
    expect(scoreTone(5)).toBe("warn");
    expect(scoreTone(4)).toBe("danger");
    expect(scoreTone(1)).toBe("danger");
  });
});

describe("MethodScores", () => {
  it("renders a single muted chip when no evaluation exists", () => {
    render(<MethodScores evaluation={undefined} />);
    const chip = screen.getByText("Not yet evaluated");
    expect(chip).toHaveAttribute("data-tone", "muted");
  });

  it("renders a muted chip for an explicit null evaluation", () => {
    render(<MethodScores evaluation={null} />);
    expect(screen.getByText("Not yet evaluated")).toHaveAttribute("data-tone", "muted");
  });

  it("renders three toned chips with justifications as tooltips", () => {
    const { container } = render(<MethodScores evaluation={evaluation()} />);
    const chips = Array.from(container.querySelectorAll(".method-score"));
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "Validity 8/10",
      "Novelty 7/10",
      "Feasibility 4/10",
    ]);
    expect(chips.map((chip) => chip.getAttribute("data-tone"))).toEqual(["ok", "warn", "danger"]);
    expect(chips[0]).toHaveAttribute("title", "Identifiable under the stated invariance.");
    expect(chips[1]).toHaveAttribute("title", "Novel coupling, adjacent to prior work.");
    expect(chips[2]).toHaveAttribute("title", "Compute budget exceeds the pilot scale.");
    expect(container.querySelector(".method-scores")).toHaveAttribute(
      "aria-label",
      "Lead evaluation scores: Validity 8/10, Novelty 7/10, Feasibility 4/10",
    );
  });
});

describe("MethodTable evaluation strip", () => {
  function renderTable(method: MethodRow) {
    const queryClient = new QueryClient();
    return render(
      <QueryClientProvider client={queryClient}>
        <MethodTable projectId="project-1" methods={[method]} />
      </QueryClientProvider>,
    );
  }

  it("shows the score strip on the catalog row when an evaluation exists", () => {
    const { container } = renderTable(methodRow({ actions: [], evaluation: evaluation() }));
    const strip = container.querySelector(".method-scores");
    expect(strip).not.toBeNull();
    expect(screen.getByText("Validity 8/10")).toBeInTheDocument();
    expect(screen.getByText("Feasibility 4/10")).toBeInTheDocument();
  });

  it("shows the muted chip on the catalog row when no evaluation exists", () => {
    renderTable(methodRow({ actions: [] }));
    expect(screen.getByText("Not yet evaluated")).toHaveAttribute("data-tone", "muted");
  });
});

describe("MethodSelector evaluation strip", () => {
  it("renders the score strip inside the option card", () => {
    render(
      <MethodSelector
        methods={[methodRow({ evaluation: evaluation() })]}
        selectedMethodId="method.example"
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("Validity 8/10")).toBeInTheDocument();
    expect(screen.getByText("Novelty 7/10")).toBeInTheDocument();
    expect(screen.getByText("Feasibility 4/10")).toBeInTheDocument();
  });

  it("renders the muted chip inside the option card without an evaluation", () => {
    render(
      <MethodSelector methods={[methodRow()]} selectedMethodId="method.example" onChange={() => {}} />,
    );
    expect(screen.getByText("Not yet evaluated")).toHaveAttribute("data-tone", "muted");
  });
});
