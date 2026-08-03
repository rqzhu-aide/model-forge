import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { ErrorState } from "../components/Feedback";
import { Panel } from "../components/Panel";

const DRAFT_KEY = "method-hub-new-project-draft";

interface ProjectDraft {
  name: string;
  question: string;
  domains: string;
  intendedUse: string;
  scope: string;
  decisionCriteria: string;
  constraints: string;
}

const emptyDraft: ProjectDraft = {
  name: "",
  question: "",
  domains: "",
  intendedUse: "",
  scope: "",
  decisionCriteria: "",
  constraints: "",
};

function initialDraft(): ProjectDraft {
  try {
    const saved = window.localStorage.getItem(DRAFT_KEY);
    return saved ? { ...emptyDraft, ...JSON.parse(saved) as Partial<ProjectDraft> } : emptyDraft;
  } catch {
    return emptyDraft;
  }
}

function lines(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

export function NewProjectPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ProjectDraft>(initialDraft);
  const hasDraft = Object.values(draft).some((value) => value.trim());

  useEffect(() => {
    if (hasDraft) window.localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    else window.localStorage.removeItem(DRAFT_KEY);
  }, [draft, hasDraft]);

  useEffect(() => {
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!hasDraft) return;
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [hasDraft]);

  const mutation = useMutation({
    mutationFn: api.createProject,
    onSuccess: async (project) => {
      window.localStorage.removeItem(DRAFT_KEY);
      setDraft(emptyDraft);
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      navigate(`/projects/${encodeURIComponent(project.project_id)}`);
    },
  });

  const update = (field: keyof ProjectDraft, value: string) => {
    setDraft((current) => ({ ...current, [field]: value }));
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    mutation.mutate({
      name: draft.name.trim(),
      research_question: draft.question.trim(),
      domains: draft.domains.split(",").map((domain) => domain.trim()).filter(Boolean),
      intended_use: draft.intendedUse.trim(),
      ...(draft.scope.trim() ? { scope: draft.scope.trim() } : {}),
      decision_criteria: lines(draft.decisionCriteria),
      constraints: lines(draft.constraints),
    });
  };

  return (
    <div className="page-stack page-stack--narrow">
      <header className="page-header">
        <p className="eyebrow">New research workspace</p>
        <h1>Define the project</h1>
        <p>This creates the formal project brief only. It does not start literature search or another research phase.</p>
      </header>

      <Panel
        title="Scientific question"
        description="Define the question and disciplinary setting that every later phase should treat as shared context."
      >
        <form className="form-stack" onSubmit={submit}>
          <label className="field">
            <span>Project name</span>
            <input value={draft.name} onChange={(event) => update("name", event.target.value)} required maxLength={180} autoFocus />
          </label>
          <label className="field">
            <span>Research question</span>
            <textarea value={draft.question} onChange={(event) => update("question", event.target.value)} rows={5} required maxLength={8000} />
            <small>State the scientific or methodological question, not a proposed answer.</small>
          </label>
          <label className="field">
            <span>Research domains</span>
            <input value={draft.domains} onChange={(event) => update("domains", event.target.value)} required placeholder="statistics, machine learning, genomics" />
            <small>Separate domains with commas.</small>
          </label>
          <label className="field">
            <span>Intended scientific use</span>
            <textarea value={draft.intendedUse} onChange={(event) => update("intendedUse", event.target.value)} rows={3} required maxLength={4000} />
            <small>For example: methods paper, biological application, or preliminary theoretical study.</small>
          </label>

          <fieldset>
            <legend>Scope and decision frame</legend>
            <div className="form-stack">
              <label className="field">
                <span>Scope</span>
                <textarea value={draft.scope} onChange={(event) => update("scope", event.target.value)} rows={3} maxLength={6000} />
                <small>Optional. State the populations, data regimes, assumptions, or methodological boundary in scope.</small>
              </label>
              <label className="field">
                <span>Decision criteria</span>
                <textarea value={draft.decisionCriteria} onChange={(event) => update("decisionCriteria", event.target.value)} rows={4} maxLength={6000} />
                <small>Optional. Enter one criterion per line, such as identifiability, statistical efficiency, or biological interpretability.</small>
              </label>
              <label className="field">
                <span>Scientific constraints</span>
                <textarea value={draft.constraints} onChange={(event) => update("constraints", event.target.value)} rows={4} maxLength={6000} />
                <small>Optional. Enter one constraint per line. Include data, computation, theory, or reporting constraints that should govern later work.</small>
              </label>
            </div>
          </fieldset>

          <p className="muted-text" role="status">
            {hasDraft ? "This draft is saved in this browser until the project is created or the draft is cleared." : "No local draft is stored."}
          </p>
          <div className="form-actions">
            <button type="button" className="button button--quiet" disabled={!hasDraft || mutation.isPending} onClick={() => setDraft(emptyDraft)}>
              Clear draft
            </button>
            <Link to="/" className="button button--quiet">Back</Link>
            <button type="submit" className="button button--primary" disabled={mutation.isPending}>
              {mutation.isPending ? "Creating project..." : "Create project"}
            </button>
          </div>
        </form>
      </Panel>
      {mutation.error ? <ErrorState error={mutation.error} title="The project was not created" /> : null}
    </div>
  );
}
