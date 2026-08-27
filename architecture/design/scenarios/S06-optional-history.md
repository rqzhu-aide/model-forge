# S06: Optional Historical Context

## Purpose

Verify that current records are the default context and history is included only
by user choice.

## Initial state

- A method has one current P3 theory record and several historical P3 runs.

## Default action

The user launches a P3 rerun without selecting historical context. The manifest
contains the current theory record, current method identity, required handoffs,
and no historical P3 run artifacts.

## Optional-history action

The user launches a later rerun and explicitly selects two historical runs. The
manifest freezes those exact records and labels them historical.

## Acceptance checks

- Historical records never masquerade as current evidence.
- The role task brief explains why each selected historical record is available.
- The run output states whether historical information changed the current
  assessment.
- Unselected history is neither copied nor mandated for reading.
