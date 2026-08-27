---
name: mf-reproducibility-checklist
description: Reproducibility discipline for empirical and implementation work — seeds, environments, data paths, and determinism. Use when designing experiments, recording an implementation record, auditing whether reported numbers can be regenerated, or preparing artifacts another researcher (or reviewer) must be able to rerun.
---

# Reproducibility Checklist

A reported number that cannot be regenerated is a claim, not evidence. Run
this checklist before any empirical record leaves your workspace.

## Identity and environment

- [ ] The exact code identity is recorded (commit or content digest), not a
      branch name or "latest".
- [ ] The runtime environment is stated: language and version, key library
      versions, hardware class where it affects results.
- [ ] Every dependency the code imports is declared; nothing is installed
      ad hoc during the run.

## Randomness

- [ ] Every source of randomness is seeded, and every seed is recorded with
      the output it produced.
- [ ] Parallel or batched runs derive seeds deterministically from a master
      seed; no wall-clock or entropy-pool seeding.
- [ ] The number of Monte Carlo replicates is stated, and the mapping from
      replicate index to seed is reproducible.

## Data and paths

- [ ] Input data is identified by content digest, not by file name or
      download date.
- [ ] All paths in the record are workspace-relative or artifact URIs; no
      absolute machine-local paths leak into the record.
- [ ] Generated artifacts (tables, figures, logs) are written to declared
      output locations and referenced by digest.

## Regeneration

- [ ] The recorded commands or scripts regenerate the headline numbers from
      the recorded inputs without manual steps.
- [ ] Runtime cost is stated (wall-clock, cores, memory) so a rerunner can
      budget.
- [ ] Known nondeterminism (threading, GPU atomics, hash ordering) is
      documented with its expected variance, not hidden.

## Reporting honesty

- Report the configuration that produced the number, not the best of an
  undocumented sweep. If a sweep happened, record its grid and selection
  rule.
- Failed or diverged replicates are part of the record: count them and say
  how they were handled.
