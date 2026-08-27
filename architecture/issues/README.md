# Issues

Living problem documents. Everything here is open or partially open; resolved
items are marked in place and the document retires to
[../archive/](../archive/README.md) when nothing remains.

## Documents

- [open-decisions-memo-2026-08-25.md](open-decisions-memo-2026-08-25.md) -
  the decision queue for Tez (D-1 through D-9 plus later items). D-1, D-7,
  and D-9 are decided and landed; the remaining items carry the coder's
  recommendations and wait on Tez.
- [context-selection-issues.md](context-selection-issues.md) - cross-phase
  context-card audit findings (2026-08-07). P0-2 is RESOLVED (folded into
  memo D-1 and landed 2026-08-26 with P5 contract 2.4.0); the remaining
  findings predate the current UI and need re-verification before further
  work is scheduled.
- [10-open-implementation-gaps.md](10-open-implementation-gaps.md) -
  structural gaps. The reviewed-basis gap is CLOSED; the reviewer-memory
  boundary remains open by design (K-7).

## Rules

- An issue document states the problem, the evidence, and the options with a
  recommendation; it does not implement.
- When Tez decides an item, record the decision in place with the date and
  the landing commit, then move the work to a plan in
  [../plan/](../plan/README.md).
