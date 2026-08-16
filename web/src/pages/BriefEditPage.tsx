import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { EmptyState, ErrorState, LoadingState } from "../components/Feedback";
import { Panel } from "../components/Panel";

/**
 * Edit the project brief — research question, scope, criteria, constraints.
 * Built on the existing brief API that previously had no page.
 */
export function BriefEditPage() {
  const { projectId } = useParams();
  const queryClient = useQueryClient();

  const briefQuery = useQuery({
    queryKey: ["project-brief", projectId],
    queryFn: () => api.getProjectBrief(projectId as string),
    enabled: Boolean(projectId),
    retry: false,
  });

  const [researchQuestion, setResearchQuestion] = useState("");
  const [scope, setScope] = useState("");
  const [decisionCriteria, setDecisionCriteria] = useState("");
  const [constraints, setConstraints] = useState("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    if (briefQuery.data && !hydrated) {
      setResearchQuestion(briefQuery.data.research_question ?? "");
      setScope(briefQuery.data.scope ?? "");
      setDecisionCriteria((briefQuery.data.decision_criteria ?? []).join("\n"));
      setConstraints((briefQuery.data.constraints ?? []).join("\n"));
      setHydrated(true);
    }
  }, [briefQuery.data, hydrated]);

  const saveMutation = useMutation({
    mutationFn: () => {
      const action = briefQuery.data?.actions[0];
      const researchQuestionTrimmed = researchQuestion.trim();
      const scopeTrimmed = scope.trim();
      return api.updateProjectBrief(projectId as string, {
        action_descriptor_id: action?.descriptor_id ?? "",
        reason: "Edited from the brief page",
        ...(researchQuestionTrimmed
          ? { research_question: researchQuestionTrimmed }
          : {}),
        ...(scopeTrimmed ? { scope: scopeTrimmed } : {}),
        decision_criteria: decisionCriteria
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
        constraints: constraints
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ["project-brief", projectId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["project-overview", projectId],
      });
    },
  });

  if (!projectId) return <EmptyState title="No project selected"><p>Pick a project first.</p></EmptyState>;
  if (briefQuery.isLoading) {
    return <LoadingState label="Loading the project brief..." />;
  }
  if (briefQuery.error) {
    return (
      <ErrorState
        error={briefQuery.error}
        title="The project brief is unavailable"
      />
    );
  }

  const basePath = `/projects/${encodeURIComponent(projectId)}`;

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">Shared scientific context</p>
          <h1>Edit project brief</h1>
          <p>
            The brief frames every run: agents read it as the standing context
            for the research question and its boundaries.
          </p>
        </div>
        <Link to={basePath} className="button button--quiet">
          Back to overview
        </Link>
      </header>

      <Panel
        eyebrow="Brief fields"
        title="Research question and boundaries"
        description="One item per line for lists. Empty optional fields are kept as-is."
      >
        <form
          className="brief-form"
          onSubmit={(event) => {
            event.preventDefault();
            saveMutation.mutate();
          }}
        >
          <label>
            Research question
            <textarea
              rows={3}
              value={researchQuestion}
              onChange={(event) => setResearchQuestion(event.target.value)}
              required
            />
          </label>
          <label>
            Scope
            <textarea
              rows={3}
              value={scope}
              onChange={(event) => setScope(event.target.value)}
              placeholder="What is in and out of scope for this study"
            />
          </label>
          <label>
            Decision criteria (one per line)
            <textarea
              rows={4}
              value={decisionCriteria}
              onChange={(event) => setDecisionCriteria(event.target.value)}
            />
          </label>
          <label>
            Constraints (one per line)
            <textarea
              rows={4}
              value={constraints}
              onChange={(event) => setConstraints(event.target.value)}
            />
          </label>
          <div className="brief-form__actions">
            <button
              type="submit"
              className="button button--primary"
              disabled={saveMutation.isPending}
            >
              {saveMutation.isPending ? "Saving..." : "Save brief"}
            </button>
            {saveMutation.isSuccess ? (
              <span className="brief-form__saved" role="status">
                Saved. The updated brief applies to your next run.
              </span>
            ) : null}
          </div>
          {saveMutation.error ? (
            <ErrorState error={saveMutation.error} title="The brief was not saved" />
          ) : null}
        </form>
      </Panel>
    </div>
  );
}
