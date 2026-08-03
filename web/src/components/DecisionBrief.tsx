import type { DecisionBrief as DecisionBriefData } from "../api/types";

export function DecisionBrief({ brief }: { brief: DecisionBriefData }) {
  return (
    <div className="decision-brief">
      <div className="decision-brief__headline">
        <span>Decision now available</span>
        <strong>{brief.current_decision}</strong>
      </div>
      <dl>
        <div>
          <dt>Most defensible conclusion</dt>
          <dd>{brief.current_conclusion}</dd>
        </div>
        <div>
          <dt>Fundamental contribution</dt>
          <dd>{brief.fundamental_contribution}</dd>
        </div>
        <div>
          <dt>What changed</dt>
          <dd>{brief.what_changed}</dd>
        </div>
        <div>
          <dt>Strongest evidence</dt>
          <dd>
            {brief.strongest_evidence.length ? (
              <ul className="link-list">
                {brief.strongest_evidence.map((item) => (
                  <li key={`${item.label}-${item.href ?? "record"}`}>
                    {item.href ? <a href={item.href}>{item.label}</a> : item.label}
                  </li>
                ))}
              </ul>
            ) : (
              "No evidence link was supplied."
            )}
          </dd>
        </div>
        <div className="decision-brief__caution">
          <dt>Main uncertainty or risk</dt>
          <dd>{brief.principal_uncertainty || brief.principal_risk}</dd>
        </div>
        <div>
          <dt>Material disagreement</dt>
          <dd>{brief.material_disagreement || "No material disagreement recorded."}</dd>
        </div>
        <div>
          <dt>Question for a rerun</dt>
          <dd>{brief.rerun_question}</dd>
        </div>
      </dl>
      {brief.available_actions.length > 0 && (
        <div className="decision-options" aria-label="Available research decisions">
          {brief.available_actions.map((action) => (
            <div key={`${action.label}-${action.consequence}`}>
              <strong>{action.label}</strong>
              <span>{action.consequence}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
