import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { BriefEditPage } from "./pages/BriefEditPage";
import { ConfigurationPage } from "./pages/ConfigurationPage";
import { NewProjectPage } from "./pages/NewProjectPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PhasePage } from "./pages/PhasePage";
import { ProfilesPage } from "./pages/ProfilesPage";
import { ProjectOverviewPage } from "./pages/ProjectOverviewPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RoleConfigurationPage } from "./pages/RoleConfigurationPage";
import { RunPage } from "./pages/RunPage";
import { SupervisedRunDetailPage } from "./pages/SupervisedRunDetailPage";
import { SupervisedRunsPage } from "./pages/SupervisedRunsPage";
import { SystemSettingsPage } from "./pages/SystemSettingsPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<ProjectsPage />} />
        <Route path="projects/new" element={<NewProjectPage />} />
        <Route path="projects/:projectId" element={<ProjectOverviewPage />} />
        <Route path="projects/:projectId/phases/:phaseId" element={<PhasePage />} />
        <Route path="projects/:projectId/runs/:runId" element={<RunPage />} />
        <Route path="projects/:projectId/settings/profiles" element={<ProfilesPage />} />
        <Route path="projects/:projectId/settings/brief" element={<BriefEditPage />} />
        <Route path="projects/:projectId/supervised" element={<SupervisedRunsPage />} />
        <Route
          path="projects/:projectId/supervised/:invocationId"
          element={<SupervisedRunDetailPage />}
        />
        <Route path="configuration" element={<ConfigurationPage />} />
        <Route path="configuration/roles/:roleId" element={<RoleConfigurationPage />} />
        <Route path="settings" element={<SystemSettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
