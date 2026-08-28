# Web UI Contract

## 1. Purpose

The Web UI helps a researcher understand current scientific state, inspect its evidence, and deliberately start or rerun a phase. It is a projection of immutable formal generations, derived record state, the current index, and run state. It is never a source of scientific truth or workflow state.

The same command service should support the Web UI and an authorized remote agent. Different clients must not produce different workflow semantics.

> **Lane scope.** Phase pages (P1-P5) drive the formal lane
> (`POST /projects/{id}/runs`, see [02b](02b-phase-run-walkthroughs.md)).
> The Runs page additionally exposes the supervised lane
> (`POST /projects/{id}/supervised-runs/start`, see
> [02a](02a-supervised-run-walkthrough.md)): start form (role, phase, brief,
> expected outputs, timeout), run detail with live log tails and outputs
> listing, cancel. Both lanes' surfaces follow the invariants below: every
> displayed state and action is a backend projection, and no surface starts
> a run implicitly.

## 2. UI invariants

### UI-001: No inferred authority

The UI must not infer completion, currency, or validity from folder existence, file timestamps, filename patterns, or arbitrary Markdown prose.

### UI-002: No automatic phase progression

Publishing a run may update available actions, but the UI must not start another run. Every launch requires a distinct user command.

### UI-003: No generic approval control

A valid run is published automatically under the authority of the launch command. The UI does not add a separate approval step. It presents the result and the next decisions available to the researcher.

### UI-004: Separate status dimensions

Publication authority, record position, method alignment, research attention, scientific outcome, and execution state must be shown separately. A single color may summarize them only when the components remain visible and the combination rule is documented.

### UI-005: Current first, history on demand

Pages display current formal records by default. Historical generations and run artifacts are available through explicit expansion or context selection, but are not mixed into the current summary.

### UI-006: Structured summary source

Summary cards use validated `DecisionBrief` and typed view fields. The UI must not select the first paragraph of a document or use heuristic text extraction as the scientific summary.

### UI-007: Consequences before launch

Before submitting a command, the UI shows the resolved method, scope, current inputs, optional context, and expected publication target. The user should understand what the run will reconsider and what it can replace or append.

### UI-008: Canonical state sources

The UI obtains current publication state, record position, alignment, attention,
and evidence eligibility from validated record-state and current-index
projections. It obtains scientific outcome and creation-time assessments from the
immutable content generation. It joins them by stable IDs and never writes back
to either source.

## 3. Backend view models

The UI consumes read-only view models produced by backend projection services.

### 3.1 Project overview

`ProjectOverviewView` contains:

- Project question and domains.
- Current literature basis summary.
- Method catalog rows.
- Active runs.
- Open high-severity attention items.
- Available user commands.

### 3.2 Method row

`MethodRowView` contains:

- Stable method ID, display name, version, and lifecycle state.
- Compact method definition summary.
- Literature provenance summary.
- Phase 3 publication position, alignment, attention count, scientific outcome, and last publication time.
- Phase 4 publication position, alignment, attention count, scientific outcome, and last publication time.
- Phase 5 publication position, alignment, attention, outcome, and manuscript state.
- Allowed actions for this method.

The row must not collapse "not run," "outdated," "inconclusive," and "failed execution" into one state.

### 3.3 Phase view

`PhaseView` contains:

- Phase purpose in direct scientific language.
- Current formal record summary.
- Exact basis and change summary.
- Alignment, outcome, and attention views.
- Primary artifacts and structured evidence links.
- Current decision brief.
- Active and recent run states.
- Run configuration schema and resolved defaults.
- Eligibility explanation and available actions.

### 3.4 Run view

`RunView` contains:

- Run ID, phase, mode, selected method, and requesting actor.
- Frozen contract, input, prepared-context, and manifest summary with digests.
- Exact stage sequence, execution groups, and current role.
- State and event times.
- Structured handoffs available for inspection.
- Validation or conflict report.
- Publication receipt when published.

Mutable progress text is clearly distinguished from formal published conclusions.

### 3.5 Decision brief view

The compact decision view displays, in this order:

1. Decision currently available.
2. Most defensible scientific conclusion.
3. Fundamental contribution or material change.
4. Strongest evidence.
5. Main assumption, uncertainty, or risk.
6. Material role disagreement.
7. Available actions and expected consequences.
8. Exact question a rerun would answer.

Each claim links to its structured statement and supporting primary artifact when available.

### 3.6 Projection freshness and empty-state provenance

Every view response identifies the current-index generation, authority-event root, projection time, and a monotone view revision. A streaming or polling transport may carry updates, but the client applies only revisions newer than the one displayed. The active-run view also gives the last run-journal sequence, journal root, event time, and a configured stale-after interval so silence is shown as stale progress rather than inferred completion.

An empty state identifies the authoritative query and projection revision that found no current slot. It must not treat an absent folder or cache as evidence that research has never run.

### 3.7 Team configuration views

Each team member (role) exposes a configuration view: identity assets (SOUL,
base configuration, library guidance) and the skill assignment surface. The
skill surface presents the bundled skill catalog against phases P1-P5, so
the researcher decides which skills a member carries into which phase;
assignments write through the role configuration API and take effect at the
next run seal, never on in-flight runs. Every view reports versions and
digests, and a write never silently overwrites a researcher customization
(scenario S13). The assignment API is
`GET /api/v1/configuration/roles/{role}/skill-assignments` (effective set
per phase with assigned-vs-default origin, the bundled catalog with content
digests plus each skill's name and description for tooltip display, and
the matrix file digest) and
`PUT /api/v1/configuration/roles/{role}/skill-assignments/{phase}`
(a skill list replaces the assignment; an empty list runs the phase with no
skills; explicit null clears back to the catalog default). "Default" means
the curated per-phase set in `resources/team/skill-defaults.json` first,
then the role's catalog union; the matrix presents the curated picks as
checked by default and the researcher edits from there. The per-phase
skill selector is specified in
[Skill Selector and Role Skill Configuration](../archive/skill-selector-and-role-skill-configuration-2026-08-26.md).

## 4. Common phase-page structure

Every phase page uses the same conceptual arrangement.

### 4.1 Current record panel

Shows what is formally current, when it was published, which run produced it, its exact basis, and what changed from the preceding generation. An empty state explains what the first run will create.

### 4.2 Scientific assessment panel

Shows alignment, scientific outcome, and open attention separately. It identifies assumptions and disagreement without converting them into software error language.

### 4.3 Evidence and detail panel

Provides progressive access from compact decision view to structured record to primary artifacts. Links preserve statement and evidence identifiers so users can return to the same location.

### 4.4 Run or rerun panel

Selects one declared run mode and collects its exact phase-specific choices, including instructions, method when applicable, Phase 1 search scope, and context. The UI submits one contract-bound `choice_values` map and does not duplicate the same decision in a second scope field. It shows resolved current inputs and the formal object that a successful run will update.

Context selection is per record: group cards toggle a whole group for convenience, and the group detail view exposes an "include in run context" choice per record, feeding `selected_context_option_ids`. Required records stay selected and locked.

The run command also accepts the researcher seed channel (ADR-019): a `seed_inputs` map from a declared supplementary input id (`pN.researcher_material`) to inline content. Seeds are additive supplementary material only - they can never replace a required published input - and freeze with researcher_seed provenance.

The run form exposes the channel as a "Supplementary material" section with three choices: none, copy into the project record (paste text or attach a small file; the bytes are content-addressed into the project artifact store and sealed with the run), or external link (for large data or material; the URL itself is sealed as `text/uri-list`, the material stays external, and anything derived from it is generated inside the project workspace). The final command review lists the attached material with its size and media type. On the run page, frozen basis entries seeded this way carry a "researcher material" provenance badge; published inputs stay unmarked.

### 4.5 History panel

Lists prior formal generations and diagnostic run records separately. The user may compare changes or select historical context for a new run. History is not included in a new run merely because the panel was opened.

## 5. Phase-specific controls

### 5.1 Phase 1

Display:

- Current literature corpus size and coverage.
- Current synthesis.
- Newly added, corrected, retracted, withdrawn, and duplicate sources from the latest run.
- Search provenance and unresolved coverage gaps.

User controls:

- Search or update focus.
- Instructions.
- Selected project context.
- Launch or rerun.

The UI should explain that Phase 1 normally expands the literature basis rather than replacing it.

### 5.2 Phase 2

Display:

- Current method catalog, including active and retired methods.
- Method versions, concise mathematical summaries, provenance, and downstream state.
- Changes from the latest catalog publication.

User controls:

- Full-catalog update or focused-method update.
- Selected method for focused mode.
- Instructions and context.
- Manual method retirement or reactivation through an explicit typed command with a reason and exact current basis.
- Launch or rerun.

The lead may recommend methods, but the UI never labels a recommendation as the user's selection.

### 5.3 Phase 3

Display:

- Read-only list of feasible current methods.
- Selected method's definition, exact version, mathematical details, and provenance.
- Current complete theory record, if one exists.
- Proof status, assumptions, counterexamples, open obligations, analyst critique, and lead conclusion.
- Alignment to the current method definition and any selected P4 context.

User controls:

- Method selection.
- Instructions.
- Current context selection.
- Optional historical-context selection, disabled when no history exists.
- Launch or rerun.

Selecting a method reveals detail and prepares a command. It does not create a durable branch or run until the user launches Phase 3.

### 5.4 Phase 4

Display:

- The same read-only feasible-method list and selected-method summary used by Phase 3.
- The four current formal Phase 4 components: evidence index, empirical synthesis, implementation record, and phase decision.
- Evidence registry with exact method version, applicability, code, data, configuration, uncertainty, and source run.
- Evidence newly added, revalidated, contradicted, or classified as outdated.
- Alignment to the current method definition and any selected P3 context.

User controls:

- Method selection.
- Preliminary or comprehensive scope on every run.
- Instructions.
- Current and optional historical context.
- Launch or rerun.

Preliminary and comprehensive describe scientific scope, not chronological order. Either may be selected when eligible.

### 5.5 Phase 5

Display:

- Exact P1, P2, P3, and P4 generations proposed as the manuscript basis.
- Eligibility and any alignment problem for each input.
- Current manuscript and change summary.
- Open review issues and their dispositions.

User controls:

- Method or manuscript target.
- Assembly or review-revision mode.
- Instructions and allowed context.
- Launch or rerun.

If P5 is ineligible, the page identifies the exact missing or mismatched record and offers navigation to the relevant phase. It does not launch the corrective run.

## 6. Action eligibility

The backend returns possible actions as typed action descriptors:

```json
{
  "schema_version": "1.0.0",
  "descriptor_id": "action.start.p3.unresolved",
  "action_type": "start_run",
  "execution_kind": "research_run",
  "project_id": "project.demo",
  "enabled": false,
  "reason_code": "METHOD_NOT_SELECTED",
  "researcher_message": "Select a current method before starting theory development.",
  "authorization": {
    "status": "direct_user",
    "user_id": "researcher.demo"
  },
  "consequence_summary": "A valid run will replace the current theory record for the selected exact method identity.",
  "issued_at": "2026-08-02T14:00:00Z",
  "command_contract": {
    "phase": "P3",
    "phase_contract_version": "2.0.0",
    "phase_contract_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
    "mode": "p3.theory_establishment"
  }
}
```

The UI may disable a control only from this backend eligibility response or a directly local incomplete form field. It must not duplicate phase dependency logic in frontend code.

An enabled action states:

- Whether it starts a research run or performs a no-run control transaction.
- Which exact method, version, record generation, run head, or formal control head it concerns, as applicable.
- Which formal current records or selected history will be used.
- The required reason and the expected scientific or eligibility consequences.
- Whether publication replaces a current record, appends evidence, updates a catalog, or withdraws one exact generation.

Typed actions include `start_run`, `cancel_run`, `retire_method`,
`reactivate_method`, and `withdraw_formal_generation`. Cancellation appears only
while an exact run remains before immutable submission. Retirement and
reactivation appear with the Phase 2 method table. Withdrawal appears in
formal-record correction controls, not in an ordinary phase-run panel. A
confirmation form is part of command construction; it is not a second generic
approval state. No control command launches a phase.

All action descriptors validate against one discriminated schema. Each branch
contains only fields relevant to that action: run-contract and publication-target
fields for `start_run`; run state and run-journal basis for `cancel_run`; method
and catalog basis for retirement or reactivation; and exact formal generation,
derived state, and control head for withdrawal. A client must not construct one
action by copying fields from another branch.

Cancellation remains available only for `created`, `preparing`, `prepared`, or
`running`. After the user submits it, the UI shows `cancellation_requested` while
active work stops cooperatively. If immutable submission won the race, the UI
refreshes the run and reports that cancellation is no longer available. It must
not offer cancellation for `submitted`, `validating`, `promoting`, `published`,
or terminal runs.

## 7. Status presentation

### 7.1 Execution state

Use only the canonical run states: `created`, `preparing`, `prepared`, `running`,
`cancellation_requested`, `submitted`, `validating`, `promoting`, `published`,
`failed`, `rejected`, `conflicted`, or `cancelled`. The display label for
`promoting` may be "Publishing," but the persisted value does not change.

### 7.2 Publication authority

| Persisted value | User-facing label |
|---|---|
| `run_local` | Run-local work |
| `submitted` | Submitted for validation |
| `validated` | Validated, not yet published |
| `formal` | Formal project record |
| `withdrawn` | Withdrawn from formal use |
| `invalid` | Invalid formal record |

### 7.3 Record position

| Persisted value | User-facing label |
|---|---|
| `current` | Current formal record |
| `historical` | Earlier formal record |
| `none` | Does not occupy a current slot |

### 7.4 Alignment

| Persisted value | User-facing label |
|---|---|
| `exact` | Exact current basis |
| `compatible` | Assessed compatible basis |
| `unassessed` | Not yet reassessed |
| `outdated` | Uses a changed or earlier basis |
| `not_applicable` | Not applicable |

### 7.5 Scientific outcome

| Persisted value | User-facing label |
|---|---|
| `supported` | Supported under stated assumptions |
| `partially_supported` | Partially supported |
| `contradicted` | Contradicted |
| `inconclusive` | Inconclusive |
| `not_assessed` | Not yet assessed |
| `not_applicable` | Not applicable |

### 7.6 Research attention

| Persisted value | User-facing label |
|---|---|
| `none` | No open research attention |
| `monitor` | Monitor |
| `reassessment_required` | Reassessment required |
| `blocking` | Blocks dependent use |

Show the count and exact questions on expansion. Research attention is not a synonym for invalidity or for an unfavorable result.

### 7.7 Evidence eligibility

| Persisted value | User-facing label |
|---|---|
| `included` | Included for the exact method |
| `excluded` | Excluded from current evidence |
| `unassessed` | Eligibility not yet assessed |
| `not_applicable` | Not applicable |

When eligibility is `excluded`, also display whether the method match is `older_method_version`, `unassessed`, or another structured reason. Do not infer eligibility from an alignment label alone.
Color is supplementary. Every status includes text, an accessible icon or shape, and an explanation. Light and dark themes must meet WCAG AA contrast for ordinary text and status indicators.

## 8. Errors, conflicts, and recovery

Messages should distinguish:

- Missing scientific prerequisite.
- Run execution failure.
- Submission validation problem.
- Publication conflict caused by a changed current basis.
- Scientific outcome that is unfavorable but formally valid.

For each non-published run, show:

- What happened.
- Whether formal current records changed.
- Whether run-local work remains available.
- The smallest user action that can proceed.

Do not present a scientifically contradicted result with a red software-error banner. Do not present a rejected schema as a scientific contradiction.

## 9. Remote operation

The Web UI and remote agent use the same read and command APIs. A remote request must expose:

- Operating identity.
- User authority or delegation.
- Resolved command before submission.
- Resulting run ID for a research run, cancellation result for a cancellation command, or transaction ID and receipt for a formal control command.
- Delegation ID and the result of project, action, target, time, and revocation checks when the operating identity is remote.

The UI should show that a run or control transaction was requested remotely and
by whom. Remote control does not weaken user authority, bypass control-command
concurrency, or allow direct formal-record mutation. The UI does not accept a
client assertion that delegation is valid.

Role outputs and agent recommendations are evidence for the researcher. They
cannot authorize `withdraw_formal_generation`. Remote retirement, reactivation,
withdrawal, and cancellation controls remain disabled until the backend resolves
an active grant covering the exact action and target. The service rechecks that
grant before commit, so expiry or revocation after form construction fails closed.

## 10. UI acceptance tests

Implementation must prove:

1. A project with no runs presents meaningful empty states and launch controls.
2. Publishing a phase updates the view but does not launch another phase.
3. P3 and P4 can each be launched after an eligible P2 method exists.
4. P4 preliminary or comprehensive scope is selectable on any eligible run.
5. Historical context is disabled when absent and excluded by default when present.
6. A method definition change updates P3, P4, and P5 alignment views without erasing their prior outcomes.
7. An inconclusive published result appears as a formal scientific outcome, not an execution failure.
8. A failed run leaves the prior current result visible and clearly distinguishes failed attempt from current record.
9. Every compact claim can navigate to its structured statement and supporting artifact.
10. UI controls match backend eligibility under refresh, concurrent publication, and remote commands.
11. Light and dark themes satisfy contrast and keyboard-navigation requirements.
12. No test depends on parsing arbitrary Markdown to determine status or available actions;
13. Deleting and rebuilding backend state projections does not change any user-visible state when the authority-event journal is unchanged.
14. Method lifecycle and formal withdrawal controls display their exact basis, reason requirement, no-run behavior, and consequence summary.
15. A stale Web or remote control command produces the same conflict response and no formal change.
16. Out-of-order view updates are discarded by revision, stale active-run progress is identified explicitly, and every empty state cites its current-index and event-root basis.
17. Cancellation and submission racing on one run produce exactly one winner:
    either `cancellation_requested` with a closed submission gate, or immutable
    `submitted` with cancellation rejected.
18. Every action descriptor validates only against its discriminated branch and
    contains no fields reserved for another action type.
19. A remote destructive action is disabled without a covering active grant and
    fails closed if that grant expires or is revoked before commit.
20. No role recommendation or agent-generated summary enables withdrawal.
