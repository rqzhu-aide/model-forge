// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MethodRow } from "../api/types";
import { MathText } from "./MathText";
import { MethodSelector } from "./MethodSelector";

afterEach(() => {
  cleanup();
});

describe("MathText", () => {
  it("renders inline $...$ math as KaTeX", () => {
    const { container } = render(<MathText text={"interaction strength $\\sigma_t$ decays"} />);
    expect(container.querySelector(".katex")).not.toBeNull();
    expect(container.textContent).toContain("interaction strength");
  });

  it("renders $$...$$ as display math", () => {
    const { container } = render(<MathText text={"$$k(x,y) = \\exp(-\\|x-y\\|^2)$$"} />);
    expect(container.querySelector(".katex-display")).not.toBeNull();
  });

  it("leaves text without delimiters as plain escaped text", () => {
    const { container } = render(<MathText text="plain \\exp mention and <b>markup</b>" />);
    expect(container.querySelector(".katex")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<b>markup</b>");
  });

  it("falls back to raw source for malformed math", () => {
    const { container } = render(<MathText text={"broken $\\notacommand{$"} />);
    expect(container.textContent).toContain("$");
  });
});

function makeMethod(overrides: Partial<MethodRow> = {}): MethodRow {
  return {
    display_name: "Kernel Estimator v2 — long description",
    summary: "A summary",
    lifecycle_state: "active",
    identity: {
      stable_id: "method.kernel",
      version: 2,
      definition_sha256: "a".repeat(64),
    },
    actions: [],
    ...overrides,
  } as MethodRow;
}

describe("MethodSelector dropdown", () => {
  it("lists only active methods by short name and reports selection", async () => {
    const onChange = vi.fn();
    render(
      <MethodSelector
        methods={[
          makeMethod(),
          makeMethod({
            display_name: "Retired Estimator v1",
            lifecycle_state: "retired",
            identity: { stable_id: "method.retired", version: 1, definition_sha256: "b".repeat(64) },
          } as MethodRow),
        ]}
        selectedMethodId=""
        onChange={onChange}
      />,
    );
    const dropdown = screen.getByRole("combobox", { name: /choose a current method/i });
    const options = Array.from(dropdown.querySelectorAll("option")).map((o) => o.textContent);
    expect(options).toEqual(["Select a method…", "Kernel Estimator v2"]);

    await userEvent.selectOptions(dropdown, "method.kernel");
    expect(onChange).toHaveBeenCalledWith("method.kernel");
  });

  it("shows an empty-state hint when no active method exists", () => {
    render(
      <MethodSelector methods={[makeMethod({ lifecycle_state: "retired" })]} selectedMethodId="" onChange={vi.fn()} />,
    );
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.getByText(/No active method is available/)).toBeInTheDocument();
  });
});
