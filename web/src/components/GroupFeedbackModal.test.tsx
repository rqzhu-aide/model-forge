// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GroupFeedbackModal } from "./GroupFeedbackModal";
import type { ContextOption } from "../api/types";

function option(partial: Partial<ContextOption> & { option_id: string }): ContextOption {
  return {
    group: "literature",
    description: null,
    feedback: null,
    required: false,
    disabled: false,
    hidden: false,
    size_bytes: 10,
    highlight_artifact_id: null,
    artifact_pointer: null,
    ...partial,
  } as ContextOption;
}

describe("GroupFeedbackModal per-option selection (FP-7.4)", () => {
  it("lets the researcher deselect one option inside the group modal", async () => {
    const onToggle = vi.fn();
    const options = [
      option({ option_id: "p1.literature_library", feedback: "Library note" }),
      option({ option_id: "p1.literature_synthesis", feedback: "Synthesis note" }),
    ];
    render(
      <GroupFeedbackModal
        group={{ key: "literature", options }}
        label="Literature review"
        projectId="project.demo"
        selectedIds={new Set(options.map((o) => o.option_id))}
        onToggle={onToggle}
        onClose={() => {}}
      />,
    );

    const boxes = screen.getAllByRole("checkbox", { name: /Include in run context/ });
    expect(boxes).toHaveLength(2);
    expect(boxes[0]).toBeChecked();

    await userEvent.click(boxes[1]!);
    expect(onToggle).toHaveBeenCalledWith("p1.literature_synthesis", false);
  });

  it("keeps required options checked and locked", () => {
    const options = [
      option({ option_id: "p1.project_brief", required: true, feedback: "Brief" }),
    ];
    render(
      <GroupFeedbackModal
        group={{ key: "literature", options }}
        label="Literature review"
        projectId="project.demo"
        selectedIds={new Set(["p1.project_brief"])}
        onToggle={() => {}}
        onClose={() => {}}
      />,
    );
    const boxes = screen.getAllByRole("checkbox", { name: /Include in run context/ });
    const box = boxes[boxes.length - 1]!;
    expect(box).toBeChecked();
    expect(box).toBeDisabled();
  });
});
