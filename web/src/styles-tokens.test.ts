/// <reference types="node" />
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * Static contract test for CSS custom properties (Audit-2026-09-02, Pkg G,
 * findings F9/F10).
 *
 * `var(--token)` WITHOUT a fallback is invalid at computed-value time when
 * `--token` is never defined, and the whole declaration is silently dropped
 * (F10: invisible timeline connectors, borderless chips, unfilled
 * highlights). This test pins the invariant that every fallback-less
 * reference resolves to a definition, and that no defined token is dead.
 *
 * Token definitions come in two forms, both matched here:
 *   1. Declaration form:        `--name: value;`            (start of line,
 *      or after `{` / `;` on the same line)
 *   2. Same-line attribute-selector assignments:
 *      `[data-phase="P1"] { --phase-hue: 210; }`
 * Class selectors such as `.button--primary:hover` must NOT be read as token
 * definitions, which is why a definition must be preceded by line start,
 * `{`, or `;`.
 */

const SRC_DIR = fileURLToPath(new URL(".", import.meta.url));
const CSS_FILES = ["styles.css", "integrity.css"]
  .map((name) => `${SRC_DIR}${name}`)
  .filter((path) => existsSync(path));

const cssText = CSS_FILES.map((path) => readFileSync(path, "utf8")).join("\n");

const DEFINITION_RE = /(?:^|[{;])\s*(--[\w-]+)\s*:/gm;
const USE_RE = /var\(\s*(--[\w-]+)\s*(,|\))/g;

function definedTokens(css: string): Set<string> {
  const found = new Set<string>();
  for (const match of css.matchAll(DEFINITION_RE)) {
    const token = match[1];
    if (token) found.add(token);
  }
  return found;
}

function usedTokens(css: string): { withFallback: Set<string>; withoutFallback: Set<string> } {
  const withFallback = new Set<string>();
  const withoutFallback = new Set<string>();
  for (const match of css.matchAll(USE_RE)) {
    const token = match[1];
    if (!token) continue;
    (match[2] === "," ? withFallback : withoutFallback).add(token);
  }
  return { withFallback, withoutFallback };
}

/**
 * Pre-existing legacy references that carry an explicit fallback, so the
 * declaration always resolves and nothing is silently dropped. They are
 * debt (the fallback value, not the theme, decides the rendering) but
 * repointing them is out of P-G scope. This list must match the scan
 * EXACTLY: any NEW undefined token — even with a fallback — fails the
 * build, and removing a reference requires updating this list.
 */
const LEGACY_FALLBACK_REFERENCES = new Set([
  "--bg-surface-2", // has `#eee` fallback
  "--border-accent", // has `#4a7dab` fallback
  "--font-mono", // has `ui-monospace, monospace` fallbacks
  "--hairline", // has `#e5e7eb` fallback
  "--space-1", // has `0.25rem` fallback
  "--space-2", // has `0.5rem` fallback
  "--space-3", // has `0.75rem` fallback
  "--space-4", // has `1rem` fallback
  "--space-5", // has `1.25rem` fallback
  "--success", // has `#3a9d5d` fallback
  "--surface-accent-muted", // has `rgba(74, 125, 171, 0.08)` fallback
  "--text-muted", // has `#666` fallback
]);

/**
 * Defined-but-unused tokens that are intentionally kept. Empty as of Pkg G:
 * the only dead token (`--canvas-strong`) was deleted by this package. Add
 * an entry here ONLY with a documented reason; prefer deleting the token.
 */
const ALLOWED_UNUSED_DEFINITIONS = new Set<string>([]);

const defined = definedTokens(cssText);
const used = usedTokens(cssText);
const allUsed = new Set([...used.withFallback, ...used.withoutFallback]);

describe("CSS token contract (styles.css + integrity.css)", () => {
  it("actually reads styles.css (guards against empty/mocked imports)", () => {
    expect(CSS_FILES.some((path) => path.endsWith("styles.css"))).toBe(true);
    expect(cssText).toMatch(/:root\s*\{/);
    expect(cssText.length).toBeGreaterThan(10000);
  });

  it("every fallback-less var(--token) reference resolves to a defined token", () => {
    const unresolved = [...used.withoutFallback].filter((token) => !defined.has(token));
    expect(unresolved).toEqual([]);
  });

  it("undefined tokens referenced with a fallback match the documented legacy list exactly", () => {
    const unresolved = [...used.withFallback].filter((token) => !defined.has(token));
    expect(new Set(unresolved)).toEqual(LEGACY_FALLBACK_REFERENCES);
  });

  it("no defined token is unused (outside the documented allowlist)", () => {
    const unused = [...defined].filter(
      (token) => !allUsed.has(token) && !ALLOWED_UNUSED_DEFINITIONS.has(token),
    );
    expect(unused).toEqual([]);
  });

  it("recognises same-line attribute-selector assignments (--phase-hue stays legal)", () => {
    // [data-phase="P1"] { --phase-hue: ... } etc. set --phase-hue per phase;
    // it must count as DEFINED so the contract above never flags it.
    expect(cssText).toMatch(/\[data-phase="P1"\]\s*\{\s*--phase-hue:/);
    expect(defined.has("--phase-hue")).toBe(true);
    expect(allUsed.has("--phase-hue")).toBe(true);
  });
});
