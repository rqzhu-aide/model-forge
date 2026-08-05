# S23: Bounded Logs Under Output Flood and Over-Long Lines

`scenario_id: s23.bounded_logs_flood_overlong`

## Purpose

Verify that streamed stdout and stderr stay within fixed bounds when Hermes
produces an output flood or a single over-long line, and that neither case
can block process completion or grow memory without bound.

## Contract under test

- ADR-012 item 7 (logs are streamed under fixed bounds):
  [ADR-012](../decisions/ADR-012-trusted-local-hermes-execution.md).
- Closure plan Block 4 (stream stdout and stderr continuously into bounded
  logs and a capped live tail; a long line or output flood cannot block
  process completion or grow memory without bound):
  [next-block-local-hermes-execution-closure](../plans/next-block-local-hermes-execution-closure.md).
- [07-contract-traceability](../07-contract-traceability.md) MH-71 (bounded
  logs) and MH-59 (mandatory append-only operational audit). Invariant
  INV-017.

## Setup

- A synthetic Hermes binary emits two distinct workloads: a sustained output
  flood (for example many megabytes of short lines) and a single line with no
  newline for many megabytes.
- The sealed run declares the normal output contract so validation can
  complete.

## Steps

1. Launch the flood workload; the supervisor streams output into the bounded
   log file and a capped live tail.
2. Launch the over-long-line workload.
3. Wait for each process to complete or time out.
4. Inspect the log file size, the live tail, peak memory, and the closure
   record.

## Expected evidence

- Both processes complete; the flood cannot block completion.
- The log file stays within the declared byte bound and the live tail within
  its cap; excess output is drained and discarded, never buffered without
  bound.
- The over-long line is handled without unbounded memory growth.
- The closure record carries the bounded diagnostics and the validation
  verdict; current state is unchanged.

## Failure conditions

- A flood or over-long line grows memory without bound or blocks process
  completion.
- The log file exceeds its declared bound.
- Bounded diagnostics are discarded before review.
- Log handling changes the validation outcome or current state.
