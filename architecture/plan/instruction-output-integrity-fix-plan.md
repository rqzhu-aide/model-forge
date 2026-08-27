# Fix Plan: Instruction, Output-Integrity, and UI Findings

Status: Active, partially implemented
Prepared: 2026-08-08
Reviewed: 2026-08-11
Basis: [Stage+role instruction changes review](../archive/stage-role-instructions-review.md)
(rounds 1 and 2). Every finding there carries file:line evidence; this plan
only sequences the fixes. Each package is sized as one dispatchable unit.

Rule for all packages: backend suite green, `validate_package.py` exit 0,
and `npm run build` plus vitest green when the frontend is touched. Leave
the tree uncommitted per current convention unless Tez says otherwise.

## Verified progress (2026-08-11)

This section marks only work demonstrated in the current tree. Unlisted work
remains open.

- FP-1 is partially complete. Layered mode, stage-role, and verbatim researcher
  direction are implemented, and task-brief rendering has regression coverage.
  The empty or placeholder and missing stage-role coordinator cases in FP-1.3
  still need direct integration tests.
- FP-2 remains open. This change set does not alter or converge output repair
  policy.
- FP-3 is complete. All six P2 stage-role templates render distinct directives
  for full catalog, focused method, and researcher proposal, with regression
  coverage.
- FP-4 is complete. Runtime examples are generated as complete, parseable,
  identity-neutral schema skeletons rather than truncated domain examples.
  Regression tests cover golden-content leakage and all five dedicated schemas.
- FP-5 is partially complete. ADR-013 records the decisions, and all four
  role-and-file guides match the current contracts. Narrative acceptance
  scenarios remain open.
- FP-6 is partially complete. The instruction-loader documentation, logged
  coordinator failure, removal of the dead instruction fallback, and template
  inventory test are complete. FP-6.1 through FP-6.3 remain open.
- FP-7 and FP-8 remain open.

## FP-1 (P0): Stop discarding user-authored instructions (finding P0-2)

1. In `run_coordinator.py`, populate `role_instructions` only when a
   template file actually exists at chain level 1-3 (stage+role, stage, or
   mode+role). Test file existence instead of calling the fallthrough
   resolver, or add an explicit `template_exists` helper to
   `default_instructions.py`.
2. Keep the mode-level template as the upstream default through
   `_apply_default_instruction` (service.py), which already runs when the
   user leaves instructions empty. With FP-1.1 in place, a user-authored
   `.instructions` choice reaches the task brief unchanged.
3. Add tests: (a) custom instruction text reaches the rendered task brief
   verbatim; (b) empty/placeholder instructions still resolve to the
   stage+role template; (c) a phase with no stage+role file falls back to
   the mode template only when the user gave no custom text.

## FP-2 (P0): Remove silent output rewriting (finding P0-3)

1. Delete content fabrication from `_auto_fill_timestamps`: no placeholder
   strings into required arrays (`handoff.completed_work`,
   `handoff.required_checks`, `literature-source.authors`), no severity
   remapping, no lineage `change_source` fabrication, no hardcoded
   `run.p2.p2-full-catalog` fallback, no text truncation.
2. Keep only mechanical repairs (missing `created_at`/`updated_at`,
   `schema_version`) and record every applied repair in the validation
   report so the published basis discloses them.
3. Everything else becomes a validation failure with a precise field-level
   message, so agents learn the schema instead of the system repairing
   silently.
4. Rename the function to describe what it does (for example
   `_apply_disclosed_mechanical_repairs`).
5. SUPERSEDED by K-2 (2026-08-19, Tez sign-off): the two lanes' divergence
   on output repair is deliberate and documented in
   `architecture/05-validation-strategy.md`. The formal lane keeps
   disclosed mechanical repairs (production path); the supervised WP-E1
   lane keeps raw-byte validation (trust-verification lane). No
   convergence work.
6. Add tests: an output missing `authors` fails validation with a precise
   error (not a fabricated author); a repair, when applied, appears in the
   validation report; the P2 lineage case fails loudly instead of being
   rewritten.

## FP-3 (P1): Mode-correct P2 stage directives (finding P1-2)

1. Rewrite the five P2 stage+role templates in mode-agnostic language:
   state that the run's authorized scope is frozen in the sealed basis
   (whole catalog or exactly one selected method) and that the role must
   not act outside it. Remove full-catalog-only phrasing ("your method
   alongside methods proposed from other perspectives").
2. Alternatively, if mode-varying stage directives are wanted later,
   extend the loader with a `<mode>.<stage_id>.<role>.md` level above the
   current level 1. This is a contract-neutral code change but needs its
   own small plan; do not bundle it into FP-3.
3. Add a rendering test that loads each P2 stage+role template in both
   modes and asserts no full-catalog-only directive survives.

## FP-4 (P1): Neutralize identities in brief-embedded examples (finding P1-3)

1. In `task_briefs._load_schema_example`, post-process the example before
   embedding: replace values of id-bearing fields (`*_id`, `run_id`,
   `stable_id`, `*_sha256`, timestamps) with `<...>` placeholders while
   preserving structure.
2. Add a brief-rendering test asserting no example stable_id or run_id
   leaks into any rendered brief.
3. Keep the truncation budget; note in the brief that placeholders must be
   replaced with run-real identities (the run_id is already given in the
   brief header).

## FP-5 (P1): Decision record for the contract changes (finding P1-1)

1. Write an ADR covering: the P3 mode rename and new revision mode, the
   P4 comprehensive gate, the new P2/P3/P4 inputs, and the two-slot
   redundancy question (`p3.current_theory` vs `p3.prior_theory`; resolve
   to one mechanism).
2. Update or add acceptance scenarios for the new modes per the project
   rule (contract changes need an ADR plus scenario updates).
3. Regenerate `role and files/by-role.md` and `by-phase.md` from the
   current contracts (finding P3-3).

## FP-6 (P2): Small backend repairs

1. `executors/fake.py`: fix `_fixture_summary` matching (lowercase prefix
   `run.p1.` style) or remove it (finding P2-5).
2. `view_models.py`: record-type-appropriate `disabled_reason` for
   missing optional records (finding P2-9).
3. `view_models.py`: deduplicate or input-identify repeated
   `finding_codes` (round 1 sub-finding).
4. `default_instructions.py`: correct the module docstring to the real
   6-level chain (finding P2-2).
5. `run_coordinator.py`: log instead of bare `except Exception: pass` in
   the instruction resolution block (finding P2-3); remove or document the
   dead role-only fallback in `role_execution.py` (finding P3-2).
6. Add the template-inventory regression test (finding P3-1): the plan's
   section 10 verification as a pytest.

## FP-7 (P2): Small frontend repairs

1. Restore the "Open validation report" link on the run page
   (finding P2-6).
2. Delete `ProjectBriefPanel` (+test) and `ScientificStatusGrid` if
   retired (finding P2-7).
3. Suppress the size badge on unavailable context groups instead of
   showing "0 B" (finding P2-8).
4. Decide on per-option deselection inside the group "more" modal
   (round 1 finding P2-4): the harness supports per-option omission, the
   cards currently do not.
5. `GroupFeedbackModal`: route artifact fetches through the API client
   instead of raw `fetch`.

## FP-8 (design decision needed, not implementation)

1. Parallel-stage isolation (round 1 open question): decide whether P1
   discovery and P5 parallel reviews need harness-enforced read scoping
   instead of instruction-only isolation. If yes, this is a contract plus
   harness change and needs its own plan.
2. Context-card granularity (round 1 finding P2-4) overlaps FP-7.4;
   decide the intended selection model first.

## Suggested order

FP-2 remains the P0 publication-integrity gate. Close the remaining FP-1 and
FP-4 acceptance checks next. FP-3 is complete. The remaining FP-5 scenario
and role/file guide work can proceed with the open FP-6 and FP-7 items. FP-8
still needs Tez's decision.
