# C-2 Plan: partial-seal correction scope (2026-08-25)

Status: IMPLEMENTED 2026-08-25 (planner-direct; production failure class
observed twice on archived runs, once on the fresh cycle).

## Failure class

A role closure seals outputs sequentially. When output k+1 fails validation,
outputs 1..k stay sealed and the closure is FAILED with correctable
findings (partial seal). The correction scope gate
(`_correction_scope_outputs`, service.py) then admitted only the SEALED
outputs: `if declared: return declared` fires whenever at least one output
sealed, so the plan-declared fallback (K5-3, written for closures that
failed before any sealing) never engages. The failed required output -
the one output the correction exists to repair - is outside the admitted
scope, Lane B cannot seal it, and revalidate re-reports
`output.required_missing`. Every such run is an unrecoverable
`correction_authorized` limbo.

Empirical hits: archived P1 run `...bf5acb79` (normalize preview admitted
0/3 required outputs; revalidate exhausted with 3 x required_missing;
scientific lane blocked by the scope gate); fresh P2 run
`...4a71023d` (method_changes unsealed while attention_items and decision
sealed). This is the dominant recovery gap observed to date.

## Design

The scope gate's purpose is blast-radius control: a correction may only
touch outputs the failed role owns. The plan-declared contract outputs for
the failed stage/role are exactly that ownership set - K5-3 already treats
them as the correctable scope when zero outputs sealed. Partial sealing is
an accident of WHERE validation failed, not a semantic difference in role
authority.

The Lane B machinery already supports absent source bytes:
`verify_correction_blast_radius` (correction_execution.py, K5-3 branch)
treats wholesale creation of an output with no sealed source as the
correction itself, and packaging pointer control is vacuous against an
absent source. The only missing piece is the gate itself.

Change (one rule): for a FAILED closure, the correctable scope is
sealed outputs UNION the failed stage/role's plan-declared contract
outputs. SUCCEEDED closures (D5 rejected-run path) keep the sealed-only
scope - no behavior change there.

## Non-goals

- No new correction lane; no atomic-sealing redesign. Revalidate on a
  still-missing output continues to report required_missing honestly -
  only a Lane B re-invocation can produce missing bytes, as designed.
- No change to finding classification, attempt bounds (HV-5.6), or the
  command acceptance path.

## Tests

- failed closure, partial seal: scope = sealed + remaining plan-declared
- failed closure, zero sealed: scope = plan-declared (K5-3 unchanged)
- succeeded closure: scope = sealed only (D5 unchanged)
