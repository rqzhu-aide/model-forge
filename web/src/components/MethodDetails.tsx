import type { MethodEvaluation, MethodRow } from "../api/types";
import { formatDate } from "../utils/format";

function ListSection({ title, values }: { title: string; values: string[] | undefined }) {
  if (!values?.length) return null;
  return (
    <section className="method-details__section">
      <strong>{title}</strong>
      <ul className="compact-list">
        {values.map((value) => <li key={value}>{value}</li>)}
      </ul>
    </section>
  );
}

function EvaluationSection({ evaluation }: { evaluation: MethodEvaluation }) {
  const axes = [
    { name: "Theoretical validity + identifiability", axis: evaluation.theoretical_validity },
    { name: "Empirical testability + computational efficiency", axis: evaluation.empirical_feasibility },
    { name: "Literature positioning + novelty", axis: evaluation.literature_positioning },
  ];
  return (
    <section className="method-details__section">
      <strong>Lead evaluation (sealed)</strong>
      {axes.map(({ name, axis }) => (
        <p key={name}>
          <b>{name}</b> — Score {axis.score}/10. {axis.justification}
          {axis.issue_refs.length ? ` ${axis.issue_refs.length} linked issue${axis.issue_refs.length === 1 ? "" : "s"}.` : ""}
        </p>
      ))}
      <p>
        Adjudicated {formatDate(evaluation.adjudicated_at)} from {evaluation.review_basis_ids.length} review
        report(s).
      </p>
    </section>
  );
}

export function MethodDetails({ method }: { method: MethodRow }) {
  return (
    <div className="method-details">
      <section className="method-details__section" aria-label="Mathematical definition">
        <strong>Mathematical definition</strong>
        <p className="preserve-lines">{method.mathematical_summary}</p>
      </section>

      {method.definition_artifact ? (
        <p>
          <a href={method.definition_artifact.href}>Open complete method record</a>
          <small> · {method.definition_artifact.information_layer} information</small>
        </p>
      ) : null}

      <dl className="record-metadata method-details__identity">
        <div><dt>Stable ID</dt><dd><code>{method.identity.stable_id}</code></dd></div>
        <div><dt>Version</dt><dd>{method.identity.version}</dd></div>
        <div>
          <dt>Definition digest</dt>
          <dd><code title={method.identity.definition_sha256}>{method.identity.definition_sha256}</code></dd>
        </div>
        {method.aliases?.length ? <div><dt>Aliases</dt><dd>{method.aliases.join(", ")}</dd></div> : null}
      </dl>

      {method.provenance_summary ? (
        <section className="method-details__section">
          <strong>Provenance</strong>
          <p>{method.provenance_summary}</p>
        </section>
      ) : null}
      {method.novelty_summary ? (
        <section className="method-details__section">
          <strong>Novelty</strong>
          <p>{method.novelty_summary}</p>
        </section>
      ) : null}
      {method.feasibility_summary ? (
        <section className="method-details__section">
          <strong>Feasibility</strong>
          <p>{method.feasibility_summary}</p>
        </section>
      ) : null}
      {method.evaluation ? <EvaluationSection evaluation={method.evaluation} /> : null}
      <ListSection title="Calculation-defining assumptions" values={method.assumptions} />
      <ListSection title="Principal risks" values={method.principal_risks} />
    </div>
  );
}

export function MethodDetailsDisclosure({ method }: { method: MethodRow }) {
  return (
    <details>
      <summary>Read complete definition and assessment</summary>
      <MethodDetails method={method} />
    </details>
  );
}
