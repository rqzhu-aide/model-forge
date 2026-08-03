# System Principles

## 1. Scientific objective

The system supports a researcher who develops, evaluates, and communicates statistical or scientific methods through repeated, user-directed runs. It must preserve the exact basis of each conclusion while keeping current information concise enough for scientific decisions.

The system coordinates research. It does not replace scientific judgment. Automated validation can establish that a record is complete, internally referential, reproducible in form, and safe to publish. It cannot by itself establish that a theorem is true, an experiment is well interpreted, or a method is scientifically important.

## 2. Actor boundaries

| Actor | May do | Must not do |
|---|---|---|
| Researcher | Start or cancel a run, select scope and context, select a method, retire a method, request a rerun, and decide how to proceed | Write formal system records outside a defined administrative correction operation |
| Authorized remote operator | Issue only the project, action, and target scope of a live researcher delegation, with both identities recorded | Reuse an expired or revoked delegation, broaden its target, or bypass the execution-time authority check |
| Research lead | Reconcile role outputs, state the current scientific conclusion, identify disagreements, and prepare the phase submission | Start another run, choose a method on the user's behalf, hide material disagreement, or publish formal records directly |
| Theorist | Develop and assess definitions, assumptions, propositions, proofs, counterexamples, and mathematical implications | Treat computational evidence as proof or write formal records directly |
| Data analyst | Develop and assess computation, study design, data quality, simulation, estimation, uncertainty, and reproducibility | Treat numerical performance as a theorem or write formal records directly |
| Outside reviewer | Independently evaluate claims, evidence, exposition, and scientific significance from a frozen review basis | Modify the reviewed manuscript or see internal material that the review contract excludes |
| Run harness | Freeze inputs, isolate writes, manage state, invoke validators, publish atomically, and record receipts | Invent a scientific conclusion, silently select context, or infer authority from file presence |
| Validator | Check schemas, references, identity, provenance, phase obligations, and declared consistency | Convert an unfavorable scientific result into a technical failure or claim that scientific truth has been proven |
| UI projection | Display formal records, active run state, evidence, uncertainty, and available commands | Become a second source of truth, infer state from arbitrary prose, or start work without a user command |

The user controls whether research work is run. The harness controls whether submitted work is structurally eligible for formal publication. Team members control the scientific content of their reports within the frozen run basis. These authorities are distinct.

## 3. System invariants

### INV-001: User-started execution

Every run or rerun must originate from an authenticated user command or an explicitly delegated command recorded as acting for that user. Cancellation requires its own authenticated, idempotent command and is allowed only before immutable submission. Completion of one phase must never start another phase automatically.

**Observable test:** Creating or publishing a record cannot enqueue a new run. A start, rerun, or cancellation with a missing, expired, revoked, or out-of-scope delegation changes nothing.

### INV-002: Explicit run scope

A run must record its phase, mode, selected method when applicable, user instructions, selected context, and role plan before role execution begins. Defaults may preselect values in the UI, but the submitted command must contain the resolved values.

**Observable test:** A run without a resolved scope cannot enter `PREPARED`.

### INV-003: Frozen scientific basis

Every prepared run must identify its required and selected inputs by stable record identity, immutable generation, and digest. It must also freeze each role's prepared context, packing budget, preference-memory inputs, and on-demand capability set. At role closure, the harness seals the exact access ledger and final role-context snapshot. A current pointer alone is not a frozen input.

**Observable test:** Changing a current record after preparation does not alter the run manifest, materialized inputs, or prepared role context. Context overflow fails explicitly or uses a frozen compaction artifact; it is never silently truncated. After role closure, the access ledger and final snapshot are immutable.

### INV-004: Run-local writes

Agents and role tools must write every artifact, including handoffs and proposed publication components, only within the role-specific active run root assigned to them. They must not write directly to harness-owned `handoffs/`, `artifacts/`, `submission/`, validation, publication, formal-record, earlier-run, or other-role locations. After a role step closes, the harness verifies the declared artifacts and copies or content-addresses the accepted outputs into harness-owned run locations.

**Observable test:** A role process has no direct formal-storage credentials. The storage broker and supported operating-system sandbox deny undeclared reads, writes outside its unique root, path traversal, symbolic-link escape, and subprocess escape. Accepted handoff and submission artifacts resolve to verified immutable outputs from that root.

### INV-005: Explicit role handoff

Information passed from one role to another must be captured in a structured handoff associated with the producing role, consuming role, frozen basis, and source artifacts. Implicit conversational memory is not a formal input.

**Observable test:** A downstream role's manifest lists each formal handoff it received.

### INV-006: Validation before publication

No run output may become a formal project record until it passes structural, identity, provenance, phase-specific, and publication-safety validation.

**Observable test:** A missing required artifact or unresolved reference prevents promotion and leaves the previous current record unchanged.

### INV-007: Atomic publication

Promotion must atomically commit the complete intended formal generations, authority events, derived record state, current index, and publication receipt, or commit none of them. Partial formal publication is prohibited.

**Observable test:** A simulated interruption at every publication step produces either the old complete state or the new complete state after recovery. Concurrent disjoint-target publications both remain present in one ordered journal; a stale same-target publication conflicts.

### INV-008: Preserved run record

Promotion must not destroy or rewrite the submitted run artifacts. Published records may copy, package, or reference validated run artifacts, but the original submitted basis must remain recoverable.

**Observable test:** The digest of every submitted artifact is unchanged after promotion.

### INV-009: Current records drive normal work

Required inputs for a new run must resolve to current formal records by default. Historical run material is included only when the phase contract requires it or the user explicitly selects it.

**Observable test:** An ordinary rerun manifest does not contain unselected historical artifacts.

### INV-010: Exact method identity

Every method-bound proof, computation, synthesis, and manuscript must identify the method by permanent stable ID, declared version, and mathematical-definition digest. The whole-file digest may be recorded for integrity but must not substitute for the mathematical-definition digest.

**Observable test:** Two method files with identical mathematical definitions and different exposition have the same definition digest but different record digests.

### INV-011: Dependency-sensitive currency

When a hard scientific dependency changes, dependent records must no longer appear exactly aligned to the current basis. They remain preserved and readable, but downstream use must expose the mismatch until reassessment or rerun.

**Observable test:** Publishing a changed method definition immediately changes the alignment projection of dependent P3, P4, and P5 records without deleting them.

### INV-012: Authority is not file depth

Primary artifacts, structured records, and compact decision views describe information depth only. Authority and currency must be read from validated record-state and current-index projections backed by append-only authority events.

**Observable test:** Moving or copying a file between presentation-layer folders does not change its authority.

### INV-013: Authority is not scientific favorability

A formally published result may be supported, partially supported, contradicted, inconclusive, or untested. Technical validation must not reject a result because its scientific outcome is negative.

**Observable test:** A complete Phase 3 report that identifies a valid counterexample can be promoted with a contradicted outcome.

### INV-014: Separate scientific dimensions

The system must not compress method alignment, need for research attention, and scientific outcome into one backend status. Each is recorded and displayed separately.

**Observable test:** A result can be exactly aligned, require further attention, and remain scientifically supported without creating a contradictory state.

### INV-015: Explicit uncertainty and disagreement

Material assumptions, unresolved issues, cross-role disagreements, and limitations must survive lead synthesis and appear in the formal scientific record and decision view.

**Observable test:** A blocking issue in a role handoff cannot disappear from the lead result without a recorded disposition and justification.

### INV-016: UI as projection

The UI must obtain displayed status, summaries, and available actions from typed backend views joining immutable formal generations, derived record state, the current index, and run state. It must not infer them from filenames, directory existence, or arbitrary Markdown text.

**Observable test:** Deleting a rendered summary cache does not change formal state or available commands. Every displayed action validates against the typed action-descriptor schema, and unavailable actions carry a stable reason.

### INV-017: Failure preserves the last valid current state

A failed, cancelled, rejected, conflicted, or interrupted run must not replace a valid current record. Its run-local evidence remains available for diagnosis according to retention policy.

**Observable test:** Each non-published terminal state leaves formal generations, authority events, record-state projections, and the current index unchanged. Concurrent submission and cancellation resolve through one compare-and-swap boundary, with exactly one accepted transition.

### INV-018: Traceable formal change

Every formal publication must have a receipt identifying the source run, validator results, prior and new generations, actor command, committed authority-event range and event root, derived projection digests, current-index generation, and time.

**Observable test:** Each current-index slot can be traced to one immutable generation, its supporting authority events, and the publication receipt that committed them.

### INV-019: Immutable content, event-derived current state

A sealed scientific generation records its authority and scientific assessments
at creation. Later supersession, alignment, attention, withdrawal, invalidation,
or evidence-eligibility changes must append authority events and rebuild derived
state. They must never rewrite the generation.

**Observable test:** Replacing a record or changing its method basis changes the
derived projection while the earlier generation bytes and digest remain
unchanged.

### INV-020: Explicit publication bindings

Every executable phase contract must map its run-local output obligations to explicit publication operations. Each binding states the applicable mode, source output IDs, append or current-slot operation, target record type and logical slot, bundled components when applicable, and expected prior generation. The sealed run manifest materializes these bindings before execution. A publisher must not infer formal targets from filenames, output kinds, or record prose.

**Observable test:** Every mode-applicable formal operation resolves to one uniquely identified frozen binding and every required output is covered by its declared operations. A missing or duplicated binding, a mode-inapplicable operation, or an undeclared output-to-target mapping blocks preparation or publication. One output may feed multiple distinct formal operations only when the executable contract declares each operation explicitly.

### INV-021: Deterministic authority-event chain

Every persisted structured-object or derived-chain digest must name one machine-readable digest contract. Structured digest payloads use RFC 8785 canonical JSON with explicit field exclusions, and authority-event journal roots use the specified binary prior-root plus content-digest construction. Artifact-pointer digests instead hash the exact referenced artifact bytes. Writers, replay, recovery, and validators use the same contract. Event types constrain which derived-state fields they may change.

**Observable test:** Independent implementations reproduce the registered Unicode and numeric digest vectors and the same authority-event journal root. Unsupported input values, undeclared exclusions, and illegal event change sets are rejected.

### INV-022: Typed user control outside research runs

Method retirement or reactivation and formal-generation withdrawal require distinct authenticated, content-digested control commands. Each command freezes the exact control head and target state, uses optimistic concurrency, creates no research run or role execution, and commits through a source-discriminated atomic receipt. An agent recommendation cannot authorize either operation. Every accepted or rejected run-start, cancellation, lifecycle, or withdrawal attempt is recorded in a separate append-only operational audit. Each audit event preserves the raw request artifact, any validated command binding, requester status, exact or explicitly unresolved target, check stage, authorization checks, complete stable error or committed effect, and a verifiable prior-root chain. Operational audit events never carry scientific authority.

**Observable test:** A stale or unauthorized control command changes nothing; a successful lifecycle command preserves mathematical method identity; and a successful withdrawal creates no replacement scientific generation or automatic historical fallback. Schema-invalid and unauthenticated attempts remain traceable from exact request bytes without inventing a trusted command or user, and replay reproduces the same operational audit root.

## 4. Scientific communication principles

### 4.1 Claims must remain connected to evidence

Any material statement in a structured scientific record should identify its assumptions, scope, assessment, and supporting or contradicting artifacts. A summary is an audit map to the underlying proof, computation, literature source, or manuscript passage. It is not a replacement for that material.

### 4.2 Role sequence is part of the research design

Role order is defined by each phase. A later role receives the frozen basis plus validated handoffs from earlier roles in the same run. The order should reflect who performs the primary work and who stress-tests it. If a material error remains after the planned sequence, the lead records the unresolved issue and a precise rerun question. The system does not silently add an unrequested repair round.

### 4.3 Current means the current formal conclusion

`Current` means that the system has published this record as the active formal record for its logical object. It does not mean final, favorable, complete in an absolute scientific sense, or immune to later revision.

### 4.4 History supports provenance, not routine context accumulation

Immutable generations and run records explain how the research changed. They are not loaded wholesale into future agent context. The system should provide compact change summaries and logical links, while the user may select older material when it is scientifically relevant.

### 4.5 Negative and partial results are first-class results

A failed proof attempt, counterexample, null result, unstable computation, or violation of an assumption may be the most important outcome of a run. If properly documented, it should become part of the formal scientific record rather than being hidden as an execution failure.

## 5. Phase-specific storage principle

The harness is shared, but publication semantics differ by phase:

- Phase 1 expands a cumulative, deduplicated literature basis and records corrections or withdrawals.
- Phase 2 updates either the full method catalog or one selected method while preserving stable method lineage.
- Phase 3 replaces the complete current theory record for the selected method.
- Phase 4 appends immutable evidence and atomically replaces four current slots for the selected method: the evidence index, empirical synthesis, implementation record, and phase decision.
- Phase 5 replaces the current manuscript and binds it to exact upstream generations.

The common harness must call the phase-specific publication policy. It must not approximate all five phases as generic file replacement.

## 6. Conflict rules

When requirements appear to conflict, apply these rules:

1. Preserve scientific provenance and the last valid formal state.
2. Do not broaden the user's authorized action.
3. Do not silently alter the frozen basis.
4. Preserve scientifically meaningful negative findings.
5. Surface the conflict to the user with the smallest action needed to resolve it.

If a run is scientifically complete but its hard dependencies changed before publication, the run is not invalid. It has a publication conflict. The submission remains preserved, but it cannot silently overwrite a current record based on a newer scientific basis.

## 7. Non-goals

This architecture does not prescribe:

- A particular agent model or inference provider.
- A particular database or object store.
- Cross-platform execution in version 1. Linux is the conformance platform for CLI-capable role isolation; another operating system may be added only after it passes the same broker and process-escape tests.
- Automatic judgment that a theorem is correct or an empirical conclusion is true.
- Automatic progression through phases.
- A single linear research path. Phases 3 and 4 may proceed independently after a suitable Phase 2 method record exists.
- Unlimited retention of redundant caches or temporary files.

Implementation details may vary if all invariants remain observable and testable.
