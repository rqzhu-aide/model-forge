# Skill Selector and Role Skill Configuration

Status: Active - approved direction, not yet implemented
Prepared: 2026-08-26, at Tez's direction
Supersedes: the deferred skill items from the 2026-08-26 evaluation
(per-run overrides and phase-scoped mapping are folded into SK-4/SK-5)

## Direction (Tez, verbatim intent)

Team member profiles are researchers who are good at their jobs. Each member,
depending on the phase (and later the stage or run), is attached to certain
skills. Not all members load all skills. There must be a configurable setting
at phase granularity at minimum, and a skill selector UI on each team member
configuration page.

## Current state (verified 2026-08-26)

- Skills attach per ROLE, not per phase: `resources/team/roles.json` declares
  `recommended_skills` and `custom_skills` per role;
  `resources/skills/manifest.json` maps skills to roles with pinned content
  digests.
- The run profile assembler installs the role's full skill set into the
  project-role profile bundle at seal time and records per-asset digests in
  the run manifest. Every phase gets the same set.
- Bundled skills today: `stat-paper-writing` (lead, theorist, analyst),
  `stat-paper-reviewer` (outside reviewer), and the four `mf-*` custom
  skills (one per role), all with real content since `9831988`.
- No UI exists for skill assignment; changing skills means editing
  `roles.json`/`manifest.json` and re-sealing.
- The run command schema has no skill field; per-run overrides do not exist.
- The design basis already anticipates selection:
  [08](../design/08-role-context-and-communication.md) section 8 - "Optional
  skills are exposed to the user and recorded when selected."

## Design

### Configuration model: one assignment matrix file

New configuration-managed resource `resources/team/skill-assignments.json`:

```json
{
  "schema_version": "1.0.0",
  "assignments": [
    {"role": "research_lead", "phase": "P5",
     "skills": ["stat-paper-writing", "mf-contribution-boundary"]},
    {"role": "theorist", "phase": "P3",
     "skills": ["stat-paper-writing", "mf-proof-dependency"]}
  ]
}
```

- Granularity: role x phase. No entry for a (role, phase) pair means the
  role's catalog default (its full recommended + bundled custom set), so the
  current behavior is the zero-configuration state and nothing migrates.
- An entry REPLACES the default for that pair (explicit beats implicit);
  it never extends it silently. An empty skill list is legal and means the
  role runs that phase with no skills.
- Every listed skill id must exist in `resources/skills/manifest.json` with
  bundled content. Unknown ids fail catalog load, not the run seal.
- roles.json and the skill manifest stay as they are; the matrix is the only
  object the UI edits.

### Seal-time resolution

`run_profile_assembler` resolves the effective set for (role, phase) at
seal: matrix entry if present, else the role default. The effective set is
installed and digest-pinned exactly as today, and the run manifest's role
definition records each installed skill with its origin (`assigned` vs
`default`) so a reviewer can tell configuration from convention.

### API

Extend the role configuration surface (`application/role_views.py`):

- `GET /api/v1/roles/{role}/skill-assignments` - the role's matrix rows
  across phases, with the available skill catalog (ids, names, digests).
- `PUT /api/v1/roles/{role}/skill-assignments/{phase}` - replace one row.
  Validated against the manifest; written to the matrix file atomically;
  takes effect at the next seal. In-flight runs are untouched (their
  profiles froze at seal).

### UI: team member configuration page

Each member's configuration page gains a skill panel:

- Rows: the available skills (from the manifest, with name + one-line
  description + digest prefix).
- Columns: phases P1-P5.
- A checked cell means the skill is assigned to that member for that phase.
  A row-level "default" marker shows the catalog default the matrix falls
  back to when no row exists.
- Save writes through the API; the panel shows the recorded digest of the
  matrix file after save so the change is auditable.
- Editorial style per the current system; the matrix must stay readable at
  10+ skills (sticky role header, no dead space).

### What changes and what does not

- No phase contract change. Skills are role resources, not contract objects;
  the digest cascade is untouched.
- No run-command change. Per-run and per-stage overrides are DEFERRED (see
  below); phase granularity is the approved unit.
- The phase instruction templates are unaffected: skills are loaded by the
  agent's profile, not named in briefs.

## Work packages

- SK-1 (small): `skill-assignments.json` schema + catalog load/validation +
  tests (unknown id rejected, empty list legal, default fallback).
- SK-2 (small-medium): seal-time resolution in `run_profile_assembler` +
  run-manifest recording with per-skill origin + tests (assigned set
  installed and digested; default unchanged without an entry).
- SK-3 (small): role configuration API (GET/PUT) + atomic matrix write +
  tests.
- SK-4 (medium): team member configuration page skill matrix UI + vitest +
  tsc + visual check against the editorial system.
- SK-5 (small): documentation - update
  [08](../design/08-role-context-and-communication.md) section 8,
  [04](../design/04-ui-contract.md) (new team-configuration section), S13
  scenario note, and this registry.

Package rules unchanged: one commit per package, explicit paths, backend
suite + `validate_package.py` green before commit; SK-4 additionally
requires vitest, tsc, and a rebuilt dist.

## Deferred (recorded, not scheduled)

- Per-stage assignment (role x stage) and per-run overrides (a run-command
  skill field). Phase granularity ships first; both extensions reuse the
  same matrix file with finer keys.
- Skill marketplace / install-from-URL. The bundle is vendored and
  digest-pinned by design.

## Open questions for Tez

1. Should the outside reviewer's skill set be user-configurable at all, or
   pinned to `stat-paper-reviewer` + `mf-review-calibration` to protect
   reviewer independence? Recommendation: configurable but warned in the UI
   (the reviewer is meant to be independent, and its skills shape its
   judgment).
2. When a matrix edit would change the effective set for a project with an
   in-flight run, should the UI show a "takes effect next run" notice?
   Recommendation: yes, always - it is one line and prevents the classic
   "I changed it but nothing happened" confusion.
