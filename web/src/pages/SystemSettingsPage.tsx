import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";
import { StatusPill } from "../components/Status";
import { sentenceCase } from "../utils/format";

export function SystemSettingsPage() {
  const settingsQuery = useQuery({
    queryKey: ["system-settings"],
    queryFn: api.getSystemSettings,
  });

  if (settingsQuery.isLoading) return <LoadingState label="Loading system settings..." />;
  if (settingsQuery.error) return <ErrorState error={settingsQuery.error} title="System settings are unavailable" />;
  if (!settingsQuery.data) return null;

  const settings = settingsQuery.data;
  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Model Forge configuration</p>
        <h1>System settings</h1>
        <p>Inspect the local service, execution adapter, and backend-managed storage used by this installation.</p>
      </header>

      <Panel
        eyebrow="Execution"
        title="Research run service"
        description="These values describe whether controlled research runs can be launched from this installation."
      >
        <dl className="status-grid system-settings-grid">
          <div><dt>Service version</dt><dd>{settings.service_version}</dd></div>
          <div>
            <dt>Execution</dt>
            <dd>
              <StatusPill tone={settings.execution_available ? "positive" : "warning"}>
                {settings.execution_available ? "Available" : "Unavailable"}
              </StatusPill>
            </dd>
          </div>
          <div><dt>Executor</dt><dd>{sentenceCase(settings.executor_kind)}</dd></div>
          <div><dt>Service address</dt><dd><code>{settings.bind_host}:{settings.port}</code></dd></div>
          <div><dt>Development mode</dt><dd>{settings.development_mode ? "Enabled" : "Disabled"}</dd></div>
          <div><dt>Database schema</dt><dd>Version {settings.database_schema_version}</dd></div>
        </dl>
        <div className="message message--neutral system-settings-message" role="note">
          <div>
            <strong>Local control only.</strong>
            <p>Remote control and remote authentication are not available in the current local build.</p>
          </div>
        </div>
      </Panel>

      <Panel
        eyebrow="Backend-managed files"
        title="Storage locations"
        description="The service owns these paths. They are shown for diagnosis and installation review."
      >
        <dl className="record-metadata system-settings-paths">
          <div><dt>Data root</dt><dd><code>{settings.data_root}</code></dd></div>
          <div><dt>Database</dt><dd><code>{settings.database_path}</code></dd></div>
          <div><dt>Artifact namespace</dt><dd><code>{settings.artifact_namespace}</code></dd></div>
          <div><dt>Architecture package</dt><dd><code>{settings.architecture_root}</code></dd></div>
          <div><dt>Web interface</dt><dd><code>{settings.frontend_dist}</code></dd></div>
        </dl>
      </Panel>

      <Panel eyebrow="Installation" title="Current installation state">
        <dl className="status-grid system-settings-grid">
          <div><dt>Projects</dt><dd>{settings.project_count}</dd></div>
          <div>
            <dt>Web interface</dt>
            <dd>
              <StatusPill tone={settings.frontend_available ? "positive" : "warning"}>
                {settings.frontend_available ? "Available" : "Unavailable"}
              </StatusPill>
            </dd>
          </div>
          <div><dt>Editing</dt><dd>{settings.settings_editable_in_ui ? "Available" : "Read only"}</dd></div>
        </dl>
        <p className="muted-text system-settings-message">{settings.settings_message}</p>
      </Panel>
    </div>
  );
}
