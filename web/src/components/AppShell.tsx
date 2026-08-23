import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";
import { matchPath, NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import type { ProjectSummary } from "../api/types";
import { ErrorState, LoadingState } from "./Feedback";
import { ProjectWorkspaceTabs } from "./ProjectWorkspaceTabs";

type Theme = "light" | "dark";

const PROJECT_SUMMARY_POLL_INTERVAL_MS = 4_000;

export function projectSummaryPollInterval(
  projects: readonly ProjectSummary[] | undefined,
): number | false {
  return projects?.some((project) => project.active_run_count > 0)
    ? PROJECT_SUMMARY_POLL_INTERVAL_MS
    : false;
}

export function changedProjectSummaryIds(
  previous: readonly ProjectSummary[] | undefined,
  current: readonly ProjectSummary[] | undefined,
): string[] {
  if (!previous || !current) return [];
  const previousById = new Map(previous.map((project) => [project.project_id, project]));
  return current.flatMap((project) => {
    const prior = previousById.get(project.project_id);
    if (!prior) return [];
    return prior.active_run_count !== project.active_run_count
      || prior.updated_at !== project.updated_at
      ? [project.project_id]
      : [];
  });
}

export async function invalidateProjectSummaryDependents(
  queryClient: QueryClient,
  projectIds: readonly string[],
): Promise<void> {
  const uniqueProjectIds = [...new Set(projectIds)];
  if (uniqueProjectIds.length === 0) return;
  await Promise.all([
    ...uniqueProjectIds.flatMap((projectId) => [
      queryClient.invalidateQueries({ queryKey: ["overview", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["phase", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["methods", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["runs", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["run", projectId] }),
      queryClient.invalidateQueries({ queryKey: ["run-events", projectId] }),
    ]),
    queryClient.invalidateQueries({ queryKey: ["profiles"] }),
  ]);
}

function initialTheme(): Theme {
  const saved = window.localStorage.getItem("model-forge-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("model-forge-theme", theme);
  }, [theme]);
  return (
    <div className="theme-toggle" role="group" aria-label="Color theme">
      <button
        type="button"
        className="theme-toggle__option"
        aria-pressed={theme === "light"}
        onClick={() => setTheme("light")}
      >
        <span aria-hidden="true">☀</span> Light
      </button>
      <button
        type="button"
        className="theme-toggle__option"
        aria-pressed={theme === "dark"}
        onClick={() => setTheme("dark")}
      >
        <span aria-hidden="true">☾</span> Dark
      </button>
    </div>
  );
}

export function projectIdFromPathname(pathname: string): string | undefined {
  const match = matchPath({ path: "/projects/:projectId/*", end: true }, pathname);
  const projectId = match?.params.projectId;
  return projectId && projectId !== "new" ? projectId : undefined;
}

export function AppShell() {
  const location = useLocation();
  const queryClient = useQueryClient();
  const previousProjects = useRef<readonly ProjectSummary[] | undefined>(undefined);
  const projectId = projectIdFromPathname(location.pathname);
  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: api.listProjects,
    refetchInterval: (query) => projectSummaryPollInterval(query.state.data),
  });
  const overviewQuery = useQuery({
    queryKey: ["overview", projectId],
    queryFn: () => api.getProjectOverview(projectId as string),
    enabled: Boolean(projectId),
  });

  useEffect(() => {
    const currentProjects = projectsQuery.data;
    if (!currentProjects) return;
    const changedProjectIds = changedProjectSummaryIds(
      previousProjects.current,
      currentProjects,
    );
    previousProjects.current = currentProjects;
    if (changedProjectIds.length === 0) return;
    void invalidateProjectSummaryDependents(queryClient, changedProjectIds);
  }, [projectsQuery.data, queryClient]);

  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">Skip to research content</a>
      <aside className="sidebar" aria-label="Model Forge navigation">
        <NavLink to="/" className="brand" aria-label="Model Forge projects">
          <span className="brand__mark" aria-hidden="true">MF</span>
          <span><strong>Model Forge</strong><small>Controlled research runs</small></span>
        </NavLink>

        <nav className="sidebar__nav" aria-label="Research projects">
          <p className="sidebar__section-label">Projects</p>
          <NavLink to="/" end className={({ isActive }) => isActive ? "sidebar-link is-active" : "sidebar-link"}>
            All projects
          </NavLink>
          <div className="sidebar__projects">
            {projectsQuery.isLoading ? <LoadingState label="Loading projects..." /> : null}
            {projectsQuery.error ? <ErrorState error={projectsQuery.error} title="Project list unavailable" /> : null}
            {projectsQuery.data?.length === 0 ? <p className="sidebar__empty">No projects yet.</p> : null}
            {projectsQuery.data?.map((project) => {
              const isCurrent = project.project_id === projectId;
              const activeRunLabel = project.active_run_count === 1
                ? "1 active run"
                : `${project.active_run_count} active runs`;
              return (
                <NavLink
                  to={`/projects/${encodeURIComponent(project.project_id)}`}
                  key={project.project_id}
                  className={isCurrent ? "sidebar-project-link is-current" : "sidebar-project-link"}
                  aria-current={isCurrent ? "page" : undefined}
                  title={`${project.name}. ${activeRunLabel}.`}
                >
                  <span
                    className="sidebar-project-link__status"
                    data-running={project.active_run_count > 0 ? "true" : "false"}
                    aria-hidden="true"
                  />
                  <span className="sidebar-project-link__name">{project.name}</span>
                  {project.active_run_count > 0 ? (
                    <span className="sidebar-project-link__count" aria-label={activeRunLabel}>
                      {project.active_run_count}
                    </span>
                  ) : null}
                </NavLink>
              );
            })}
          </div>
        </nav>

        <nav className="sidebar__footer" aria-label="Hub tools">
          <NavLink to="/projects/new" className={({ isActive }) => isActive ? "sidebar-link is-active" : "sidebar-link"}>
            <span aria-hidden="true">+</span> New project
          </NavLink>
          {projectId ? (
            <NavLink
              to={`/projects/${encodeURIComponent(projectId)}/settings/profiles`}
              className={({ isActive }) => isActive ? "sidebar-link is-active" : "sidebar-link"}
            >
              <span aria-hidden="true">@</span> Profiles and skills
            </NavLink>
          ) : null}
          <ThemeToggle />
          <NavLink to="/configuration" className={({ isActive }) => isActive ? "sidebar-link is-active" : "sidebar-link"}>
            <span aria-hidden="true">⚙</span> Configuration
          </NavLink>
          <NavLink to="/settings" className={({ isActive }) => isActive ? "sidebar-link is-active" : "sidebar-link"}>
            <span aria-hidden="true">:</span> System settings
          </NavLink>
          <p>Nothing runs without a user-authorized command.</p>
        </nav>
      </aside>

      <div className="app-main">
        <header className="mobile-header">
          <NavLink to="/" className="brand"><span className="brand__mark">MF</span><strong>Model Forge</strong></NavLink>
          <details className="mobile-menu">
            <summary>Navigate</summary>
            <nav>
              <NavLink to="/">Projects</NavLink>
              <NavLink to="/projects/new">New project</NavLink>
              {projectId ? <NavLink to={`/projects/${projectId}/settings/profiles`}>Profiles</NavLink> : null}
              <NavLink to="/configuration">Configuration</NavLink>
              <NavLink to="/settings">System settings</NavLink>
            </nav>
          </details>
        </header>
        <main id="main-content" className="content" tabIndex={-1}>
          {projectId ? (
            <ProjectWorkspaceTabs
              projectId={projectId}
              overview={overviewQuery.data}
              loading={overviewQuery.isLoading}
            />
          ) : null}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
