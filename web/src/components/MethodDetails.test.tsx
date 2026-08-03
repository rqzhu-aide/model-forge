import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { MethodRow } from "../api/types";
import { MethodDetailsDisclosure } from "./MethodDetails";

const method: MethodRow = {
  identity: {
    stable_id: "method.robust-score",
    version: 3,
    definition_sha256: "0123456789abcdef0123456789abcdef",
  },
  display_name: "Robust score estimator",
  aliases: ["RSE"],
  lifecycle_state: "active",
  summary: "A robust estimator for contaminated samples.",
  mathematical_summary: "\\hat{theta} = argmin_theta \\sum_i rho(x_i - theta)",
  assumptions: ["Independent observations", "Finite second moment"],
  provenance_summary: "Derived from the current literature basis.",
  novelty_summary: "Adapts the score under structured contamination.",
  feasibility_summary: "The optimization is convex under the stated loss.",
  principal_risks: ["Sensitivity to the tuning parameter"],
  definition_artifact: {
    artifact_id: "artifact.method.robust-score.v3",
    label: "Method record",
    information_layer: "structured",
    href: "/artifacts/method.robust-score.v3",
  },
  phase_statuses: {},
  actions: [],
};

describe("MethodDetailsDisclosure", () => {
  it("keeps the complete scientific definition accessible without flattening it into the table", () => {
    const markup = renderToStaticMarkup(<MethodDetailsDisclosure method={method} />);

    expect(markup).toContain("<details>");
    expect(markup).toContain("Read complete definition and assessment");
    expect(markup).toContain("Mathematical definition");
    expect(markup).toContain("argmin_theta");
    expect(markup).toContain("Independent observations");
    expect(markup).toContain("Sensitivity to the tuning parameter");
    expect(markup).toContain('href="/artifacts/method.robust-score.v3"');
    expect(markup).toContain("0123456789abcdef0123456789abcdef");
  });
});
