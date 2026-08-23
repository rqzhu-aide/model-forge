# UI Design Audit: Model Forge Web Interface (2026-08-21)

Scope: every workspace tab and supporting page of the production UI
(light + dark themes), driven live against the production database
(server in default posture, executor=disabled) with a headless Chromium.
Method: DOM/accessibility extraction, computed-style capture (fonts,
colors), WCAG contrast computation, console monitoring, full-page
screenshots (see `screenshots/`).

Pages walked: Projects, Overview, phase tabs P1-P5, published Run page,
failed Run page (pre-K5-2 failure), Supervised runs, Profiles and skills,
Brief editor, Configuration, Role configuration, System settings.

Audit questions (Tez, 2026-08-21):
1. Is the interface intuitive; are titles and wording consistent with
   statistical research workflow and community habits?
2. Fonts and colors: legibility, decision-relevant visibility, distinct
   colors for critical decisions.
3. Consistency of patterns across the phase tabs.

## Executive summary

15 pages, 0 page-load failures, 1 console error source. The design system
is fundamentally sound: one font stack (Inter, 15px base, clear
32/20/15 hierarchy), near-universal WCAG AA contrast, a working dark
theme with adapted semantic colors, and an honest research-integrity
vocabulary (frozen basis, sealed command, current record) that fits the
statistical research workflow. The findings concentrate where Tez
predicted: naming drift between contract and UI, decision-critical states
that do not look decision-critical, and tone inconsistencies for identical
semantics across tabs.

| # | Finding | Severity | Area |
|---|---|---|---|
| 1 | Phase naming drift: three sources disagree (contract JSON, phase docs, sidebar tabs) | High | Wording |
| 2 | P2 artifacts list duplicate React keys (10 console errors) | Medium | Console bug |
| 3 | "Output needs correction" pill is muted grey on the failed-run page | Medium-High | Decision visibility |
| 4 | P1 status card shows three contradictory signals at once | Medium-High | Decision clarity |
| 5 | "Needs attention" on nearly every tab of a healthy project | Medium | Signal fatigue |
| 6 | Same semantic state, different colors within and across tabs | Medium | Color consistency |
| 7 | Historical failed runs: "needs correction" but no findings, no controls | Medium | UX dead end |
| 8 | Broken ":" icon on System settings; "@" on Profiles and skills | Low | Polish |
| 9 | Primary CTA label "Review this run" reads as inspection, not launch | Low | Wording |
| 10 | Duplicate h2 repeating the h1 text on P1/P2 | Low | Structure |
| 11 | Danger button contrast 4.16:1 (borderline vs AA 4.5:1) | Low | Contrast |

## Findings

### 1. Phase naming drift (High, wording)

Three naming sources disagree on the same phases:

| Phase | Sidebar tab + tooltip (`format.ts`) | Page h1 (contract JSON) | Phase doc title |
|---|---|---|---|
| P1 | Literature / Literature basis | Literature basis | Literature Basis |
| P2 | Methods / Method catalog | **Method development** | Method Catalog |
| P3 | Theory / Theory development | Theory development | Theory Development |
| P4 | Evidence / Empirical evaluation | **Empirical development** | Empirical Evaluation |
| P5 | Manuscript / Manuscript assembly | **Manuscript assembly and revision** | Manuscript Assembly |

The h1 comes from `architecture/contracts/phases/*.json` (rendered via
`phase.name` in PhasePage.tsx:83); the tabs use the frontend's own
`phaseNames`/`phaseShortNames`. A researcher reading the tab "Methods"
lands on a page titled "Method development" whose contract document is
titled "Method Catalog". For a tool whose selling point is exact
provenance, the phase names should be single-sourced. Recommendation:
make the contract JSON the one authority and render tabs from the API
(phaseNames/phaseShortNames deleted), or align all three on the doc
titles. Needs a wording decision from Tez (which names win).

### 2. P2 artifacts list duplicate React keys (Medium, console bug)

`04-phase-P2` logs 10 identical React errors: "Encountered two children
with the same key `artifact.f4039bcdcf1e2cce...`". PhasePage.tsx:223 keys
the phase artifacts list by `artifact.artifact_id`, and the P2 artifacts
feed contains the same artifact id once per recent run (10 runs). React
warns the behavior is unsupported (children may be duplicated or omitted
across updates). Fix: composite key (artifact_id + run/sequence), or
deduplicate the feed server-side. Verified: key value captured live; the
list renders today, so this is latent, not cosmetic-only.

### 3. Decision-critical pill is grey (Medium-High, decision visibility)

On the failed-run page the recovery pill "Output needs correction" -
the single element telling the researcher an action choice exists -
renders in `--muted` grey, visually identical to neutral metadata like
"Recorded snapshot". The destructive "Request cancellation" button gets a
distinct red style; the recovery state that actually asks for a decision
gets none. Recommendation: give `needs_output_correction` (and
`correction_exhausted`) a distinct action color (amber or indigo family)
so the decision affordance is findable at a glance.

### 4. P1 status card shows contradictory signals (Medium-High, decision clarity)

The P1 phase-status card simultaneously presents: "Unassessed" (amber
pill), "Attention: Blocks dependent use" (red pill), and outcome
"Supported under stated assumptions" (green). The researcher question
"can I build on this?" has no single visible answer; three competing
colors compete in one card. Recommendation: one headline verdict
(compute the blocking state first, then show the assessment outcome as
secondary detail), e.g. headline "Blocked for dependent use" with the
green outcome demoted to a sub-line.

### 5. "Needs attention" everywhere (Medium, signal fatigue)

On a freshly published, healthy project the workspace tabs/sidebar label
P1-P4 all "Needs attention" (P5 "No current record"). When every tab
carries the same warning, the warning stops routing attention. The label
appears to derive from open attention items regardless of whether the
tab itself has an actionable decision. Recommendation: differentiate
"has open attention items" (informational, muted) from "action required
on this phase" (warning color), or show the open-item count and reserve
the colored label for blocker-class items.

### 6. Same state, different colors (Medium, color consistency)

- P1: "Attention: Blocks dependent use" appears as a red status-pill AND
  as an ink (neutral) compact-phase-status on the same page.
- "Unassessed" is amber on P1 but the identical state is neutral ink on
  P2 ("Not yet assessed") and muted on P3.
- "Unavailable" is red on Profiles (role unavailable) but amber on
  System settings (executor unavailable). Defensible as severity
  grading, but undocumented; today it reads as drift.
Recommendation: a tone table (state -> tone -> color) in one place
(`Status.tsx` already centralizes some of this), applied everywhere.

### 7. Historical failed runs are a UX dead end (Medium)

Run `...6c5396b4` (failed 2026-08-20, pre-K5-2) shows the pill "Output
needs correction" but zero findings, no correction controls
(`available_recovery_controls: []`, correctable/blocking counts 0), and
a "What to do next" that amounts to "go back and rerun". This is
consistent with the backend (the run predates findings propagation), so
it is not a logic bug - but the page contradicts itself for every
historical failure in the database. Recommendation: when
recovery_summary says needs_output_correction but no findings/controls
exist, render an explicit "recorded before the correction lane existed;
rerun is the recovery path" note instead of the bare dead end.

### 8. Broken/odd sidebar icons (Low, polish)

AppShell.tsx:192 ships a literal ":" as the System settings icon;
"Profiles and skills" uses "@". "Configuration" uses a real gear glyph.
Replace with intended glyphs (or drop icons for a text-only rail).

### 9. Primary CTA wording (Low, wording)

Every phase tab's primary action is "Review this run" (opens the review
dialog "Start this exact run?" -> "Start this run"). The review-then-
confirm flow is right for a sealed-basis launch; the label undersells
it. "Review and start run..." would set the correct expectation.
(Verified: disabled state correctly explains the executor-unavailable
reason in plain language - good.)

### 10. Duplicate h2 = h1 text (Low, structure)

P1 and P2 render an h2 identical to the page h1 ("Literature basis",
"Method development") as the current-record section heading. Redundant
heading noise; rename the section (e.g. "Current record: Literature
basis") or drop it.

### 11. Danger button contrast (Low)

button--danger red (#cf3145) on light red (#fce4e8) measures 4.16:1 -
passes for large/bold text (3:1) but a hair under AA for 15px bold
(4.5:1). All other measured pairs pass: body 16.3:1, muted 5.0:1, status
colors ~5.0:1, primary button 6.3:1, sidebar 7-16:1, dark-theme pills
all > 7:1.

## What is working (keep)

- Single Inter stack, 15px base, disciplined heading hierarchy.
- Dark theme with properly adapted semantic pill colors (verified live).
- Research-integrity vocabulary is consistent and domain-appropriate:
  "What a run command seals", "Frozen scientific basis", "User direction
  fixed at launch", "Nothing runs without a user-authorized command",
  idempotency explained on the supervised-run form.
- Review-then-confirm pattern for consequential actions (run launch,
  cancellation, provisioning), with plain-language consequence summaries.
- Disabled actions explain WHY (executor-unavailable message names the
  exact remedy).
- Cross-tab panel grammar is stable: Configure -> current record ->
  artifacts -> recent runs -> metadata -> sealed-basis details; absent
  sections degrade gracefully (P3/P4/P5).

## Testing notes

- Posture: executor=disabled (default). Run-start controls were
  therefore disabled everywhere; their disabled-reason messaging was
  audited instead of the launch flow (the launch flow itself was
  exercised in the K-5 production runs).
- Not covered: NewProjectPage form validation, BriefEditPage save flow,
  GroupFeedbackModal (no data state produced it), responsive/mobile
  widths (audit viewport 1280px).
- Console was clean on every page except P2 (finding 2).
