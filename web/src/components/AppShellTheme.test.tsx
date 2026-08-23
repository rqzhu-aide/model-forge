// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeToggle } from "./AppShell";

function stubSystemTheme(theme: "light" | "dark") {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-color-scheme: dark)" ? theme === "dark" : theme === "light",
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })) as unknown as typeof window.matchMedia;
}

afterEach(cleanup);

beforeEach(() => {
  window.localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("ThemeToggle", () => {
  it("defaults to the system preference when nothing is saved", () => {
    stubSystemTheme("dark");
    render(<ThemeToggle />);
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
  });

  it("prefers the saved theme over the system preference", () => {
    stubSystemTheme("dark");
    window.localStorage.setItem("model-forge-theme", "light");
    render(<ThemeToggle />);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "true");
  });

  it("switches theme on click and persists the choice", async () => {
    stubSystemTheme("light");
    const user = userEvent.setup();
    render(<ThemeToggle />);
    expect(document.documentElement.dataset.theme).toBe("light");

    await user.click(screen.getByRole("button", { name: "Dark" }));

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(window.localStorage.getItem("model-forge-theme")).toBe("dark");
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "false");
  });
});
