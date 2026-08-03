import { describe, expect, it } from "vitest";
import { compactScientificStatusSummary, runStateTone } from "./Status";

describe("compact scientific status", () => {
  it("distinguishes the researcher-facing state dimensions", () => {
    expect(compactScientificStatusSummary(undefined).stateLabel).toBe("Not run");
    expect(compactScientificStatusSummary({ record_position: "current" }).stateLabel).toBe("Current");
    expect(compactScientificStatusSummary({ alignment: "outdated" }).stateLabel).toBe("Outdated");
    expect(compactScientificStatusSummary({ alignment: "unassessed" }).stateLabel).toBe("Unassessed");
    expect(compactScientificStatusSummary({ attention: "blocking" }).attentionLabel).toBe("Attention: Blocks dependent use");
    expect(compactScientificStatusSummary({
      record_position: "current",
      scientific_outcome: "contradicted",
    }).outcomeLabel).toBe("Contradicted");
  });

  it("preserves alignment, attention, and outcome at the same time", () => {
    const summary = compactScientificStatusSummary({
      alignment: "outdated",
      attention: "reassessment_required",
      scientific_outcome: "inconclusive",
    });

    expect(summary.stateLabel).toBe("Outdated");
    expect(summary.attentionLabel).toBe("Attention: Reassessment required");
    expect(summary.outcomeLabel).toBe("Inconclusive");
  });

  it("uses distinct terminal run tones", () => {
    expect(runStateTone("cancelled")).toBe("neutral");
    expect(runStateTone("conflicted")).toBe("warning");
    expect(runStateTone("failed")).toBe("danger");
    expect(runStateTone("rejected")).toBe("danger");
  });
});
