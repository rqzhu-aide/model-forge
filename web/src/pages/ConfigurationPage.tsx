import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { RoleHealthReportView } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { StatusPill, configurationOverallTone } from "../components/Status";

export function RoleConfigurationCard({ role }: { role: RoleHealthReportView }) {
  const detailHref = `/configuration/roles/${encodeURIComponent(role.role_id)}`;
  return (
    <article className="profile-card config-role-card">
      <header>
        <div>
          <p className="eyebrow">Role definition</p>
          <h2>
            <Link to={detailHref}>{role.display_name}</Link>
          </h2>
          <p>{role.detail}</p>
        </div>
        <StatusPill tone={configurationOverallTone(role.overall_status)}>
          {role.overall_status}
        </StatusPill>
      </header>
      <dl className="profile-science-grid">
        <div><dt>Role id</dt><dd><code>{role.role_id}</code></dd></div>
        <div><dt>Hermes profile</dt><dd>{role.profile_name ?? "No profile assigned"}</dd></div>
        <div>
          <dt>Conditions</dt>
          <dd>{role.conditions.length > 0 ? role.conditions.join(", ") : "None"}</dd>
        </div>
      </dl>
      <p className="config-role-card__link">
        <Link to={detailHref} className="button button--small button--quiet">
          Inspect role definition
        </Link>
      </p>
    </article>
  );
}

export function ConfigurationPage() {
  const healthQuery = useQuery({
    queryKey: ["configuration-health"],
    queryFn: api.getConfigurationHealth,
  });

  if (healthQuery.isLoading) {
    return <LoadingState label="Loading role configuration..." />;
  }
  if (healthQuery.error) {
    return <ErrorState error={healthQuery.error} title="Role configuration is unavailable" />;
  }
  if (!healthQuery.data) {
    return (
      <EmptyState title="No role configuration is available">
        <p>The configuration service returned no data.</p>
      </EmptyState>
    );
  }

  const health = healthQuery.data;
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Method Hub configuration</p>
        <h1>Role definitions and installation health</h1>
        <p>
          Inspect the four research roles, their SOUL definitions, configuration files, and
          skill installation status before provisioning a profile.
        </p>
      </header>

      <Panel
        eyebrow="Installation"
        title="Configuration health"
        description={`Hermes root: ${health.hermes_root}`}
      >
        <dl className="status-grid">
          <div>
            <dt>Overall status</dt>
            <dd>
              <StatusPill tone={configurationOverallTone(health.overall_status)}>
                {health.overall_status}
              </StatusPill>
            </dd>
          </div>
          <div><dt>Hermes available</dt><dd>{health.hermes_available ? "Yes" : "No"}</dd></div>
          <div><dt>Roles</dt><dd>{health.roles.length}</dd></div>
        </dl>
        {!health.hermes_available ? (
          <div className="message message--warning" role="note">
            <div>
              <strong>Hermes is not available.</strong>
              <p>
                Role definitions can still be inspected, but provisioning requires a Hermes
                installation at the configured root.
              </p>
            </div>
          </div>
        ) : null}
        {health.conditions.length > 0 ? (
          <p className="muted-text">Conditions: {health.conditions.join(", ")}</p>
        ) : null}
      </Panel>

      {health.roles.length === 0 ? (
        <EmptyState title="No role definitions are installed">
          <p>Provisioning requires the role resource catalog to define at least one role.</p>
        </EmptyState>
      ) : (
        <div className="profile-list">
          {health.roles.map((role) => <RoleConfigurationCard role={role} key={role.role_id} />)}
        </div>
      )}
    </div>
  );
}
