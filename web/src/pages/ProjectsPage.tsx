import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { formatDate } from "../utils/format";

export function ProjectsPage() {
  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: api.listProjects });

  return (
    <div className="page-stack">
      <header className="page-header page-header--with-action">
        <div>
          <p className="eyebrow">Research workspace</p>
          <h1>Your research projects</h1>
          <p>Open a project to inspect formal research state or explicitly start a new controlled run.</p>
        </div>
        <Link to="/projects/new" className="button button--primary">Create a project</Link>
      </header>

      {projectsQuery.isLoading ? <LoadingState label="Loading projects…" /> : null}
      {projectsQuery.error ? <ErrorState error={projectsQuery.error} title="Projects are unavailable" /> : null}
      {projectsQuery.data?.length === 0 ? (
        <EmptyState
          title="No research project exists yet"
          action={<Link to="/projects/new" className="button button--primary">Create the first project</Link>}
        >
          <p>Start with a research question. The system will create an empty workspace without running a phase.</p>
        </EmptyState>
      ) : null}

      {projectsQuery.data?.length ? (
        <div className="project-grid">
          {projectsQuery.data.map((project) => (
            <article className="project-card" key={project.project_id}>
              <div>
                <p className="eyebrow">{project.active_run_count} active run{project.active_run_count === 1 ? "" : "s"}</p>
                <h2>
                  <Link to={`/projects/${encodeURIComponent(project.project_id)}`}>{project.name}</Link>
                </h2>
                <p>{project.research_question}</p>
              </div>
              <div className="tag-list" aria-label="Research domains">
                {project.domains.map((domain, index) => <span key={`${domain}-${index}`}>{domain}</span>)}
              </div>
              <footer>
                <small>Updated {formatDate(project.updated_at)}</small>
                <Link to={`/projects/${encodeURIComponent(project.project_id)}`}>Open project</Link>
              </footer>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}
