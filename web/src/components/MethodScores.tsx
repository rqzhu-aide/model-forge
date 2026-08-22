import type { MethodEvaluation } from "../api/types";

/**
 * Sealed lead evaluation scores (ADR-017 D4): a compact three-chip strip
 * showing the lead's adjudicated per-axis scores. Justifications stay in the
 * chip tooltips and the method details disclosure; methods without an
 * evaluation block render a muted "Not yet evaluated" chip.
 */

export function scoreTone(score: number): "ok" | "warn" | "danger" {
  if (score >= 8) return "ok";
  if (score >= 5) return "warn";
  return "danger";
}

export function MethodScores({ evaluation }: { evaluation: MethodEvaluation | null | undefined }) {
  if (!evaluation) {
    return (
      <span className="method-scores">
        <span className="method-score" data-tone="muted">
          Not yet evaluated
        </span>
      </span>
    );
  }
  const axes = [
    { label: "Validity", axis: evaluation.theoretical_validity },
    { label: "Feasibility", axis: evaluation.empirical_feasibility },
    { label: "Novelty", axis: evaluation.literature_positioning },
  ];
  const ariaLabel = axes.map(({ label, axis }) => `${label} ${axis.score}/10`).join(", ");
  return (
    <span className="method-scores" role="group" aria-label={`Lead evaluation scores: ${ariaLabel}`}>
      {axes.map(({ label, axis }) => (
        <span
          className="method-score"
          data-tone={scoreTone(axis.score)}
          title={axis.justification}
          key={label}
        >
          {label} {axis.score}/10
        </span>
      ))}
    </span>
  );
}
