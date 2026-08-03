import { Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { NewProjectPage } from "./pages/NewProjectPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PhasePage } from "./pages/PhasePage";
import { ProfilesPage } from "./pages/ProfilesPage";
import { ProjectOverviewPage } from "./pages/ProjectOverviewPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RunPage } from "./pages/RunPage";
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
        <Route path="settings" element={<SystemSettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
