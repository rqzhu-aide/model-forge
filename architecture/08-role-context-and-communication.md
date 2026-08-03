# Role, Context, and Communication Contract

## 1. Purpose

Research quality depends on more than assigning a task to an agent. Each role
must receive a reproducible scientific stance, phase instruction, context,
memory policy, skills, knowledge resources, tools, and output contract.

This document makes those inputs part of the controlled run. It does not define
the final prompt wording. It defines what a programmer must assemble, freeze,
expose, and validate.

## 2. Versioned role profile

Every role stage uses a versioned `RoleProfileManifest`. The manifest records:

- profile ID, version, and content digest;
- role, applicable phases, applicable modes, and exact `applicable_stage_ids`;
- scientific stance, also called the role's soul;
- phase-specific task instruction;
- required output and handoff contracts as immutable artifact pointers with digests;
- context visibility and isolation rules;
- memory policy;
- required and optional skills with immutable version and digest pointers;
- knowledge resources, retrieval policies, and immutable adapter-manifest version and digest pointers;
- allowed tools, libraries, execution limits, and immutable tool-manifest version and digest pointers;
- reviewer-isolation rules when applicable.

The scientific stance describes durable commitments, not a fictional persona. It
states the questions the role habitually asks, the evidence it treats as
decisive, the errors it must actively seek, and the claims it must not make.

A profile update creates a new immutable version. Every run freezes the exact
profile manifest used by each role. A completed run is never reinterpreted under
a later profile.

### 2.1 Frozen run role step

Every `RunRoleStep` freezes:

- `stage_id` and `execution_group_id`;
- serial or parallel execution;
- exact role-profile artifact version and digest;
- the exact artifact input allowlist with versions, digests, and locators;
- exact model, tokenizer, context-packing policy, and capacity declarations;
- the versioned project-preference-memory binding or an explicit disabled value;
- output and handoff identifiers and schemas;
- one role-specific run-local write root;
- the prepared-context digest before execution and the closed
  `RoleContextSnapshot` digest after execution.

A role cannot resolve an input outside its capabilities or write outside its
root. It writes handoffs and proposed publication components under that same
root. After the role step closes, the harness verifies them and copies or
content-addresses accepted outputs into harness-owned shared run locations.
Sharing an execution group permits parallel execution but does not grant mutual
visibility. Every parallel role receives the same frozen group-start state.

The manifest role step is a frozen recipe, not an execution record. It may name
future output IDs and upstream obligations, but it must not contain unknown
future artifact, access-ledger, start-time, or terminal-status digests.

Before execution, the harness persists an immutable `PreparedRoleContext` with
project and run identity, the exact context structure, deterministic packing
basis, rendered artifact, six-field projection digest, and whole-record digest.
It then persists `RoleInvocationStart`, which copies and hashes the complete
manifest role-plan entry and binds the resolved profile, actual input artifacts,
output contracts and paths, capability set, write root, and prepared-context
record. The role process may start only after both records validate.

After execution, the harness persists `RoleInvocationClosure`. It binds the
start digest, terminal status, exact final `RoleContextSnapshot` and access-ledger
head, verified produced outputs, accepted harness-owned artifacts and handoffs,
and failure or cancellation information. A later role start may consume an
upstream output only from a successful closure and only with the exact accepted
artifact digest. The immutable start is never revised to add information learned
at closure.
## 3. Role-specific scientific stance

| Role | Primary responsibility | Required challenge |
|---|---|---|
| Research lead | Integrate the scientific argument, preserve disagreement, and present the user's decision | Do not choose a branch, hide uncertainty, or publish directly |
| Theorist | Define mathematical objects, assumptions, claims, proofs, counterexamples, and boundaries | Do not treat simulation or empirical performance as proof |
| Data analyst | Define study design, implementation, data provenance, computation, uncertainty, and reproducibility | Do not treat a successful computation as a general theorem |
| Outside reviewer | Assess the frozen manuscript as an independent first-time reader | Do not edit the manuscript or inspect excluded internal deliberation |

Phase instructions narrow these responsibilities without changing them. For
example, the theorist performs primary work in Phase 3 and a mathematical
fidelity audit in Phase 4.

## 4. Enforcement boundary and threat model

### 4.1 Threat model

Treat the role process, model-generated tool calls, installed skills, and
command-line programs as untrusted with respect to project authority. They may
request the wrong artifact, follow an injected instruction, scan a filesystem,
read environment variables, invoke another process, or attempt a network or path
escape. The protected assets are:

- formal and current project records;
- other roles' workspaces and unpublished handoffs;
- storage, network, and secret credentials;
- user-unselected history and project preference memory;
- Phase 5 internal deliberation hidden from the outside reviewer;
- harness-owned submission, journal, receipt, and projection storage.

Compromise of the host kernel or a platform administrator is outside the
version 1 threat model. A trusted harness or broker defect remains a system
failure and must be visible through validation and audit logs.

### 4.2 Portable storage boundary

The capability broker is the only storage interface available to a role. The
harness gives it opaque capabilities bound to one run, stage, operation, exact
immutable artifact, read or write action, maximum use count, and expiry. The
broker checks the frozen role plan for every operation. It never accepts an
agent-supplied project path as authority.

The role process receives no project-store or formal-store credential. It also
receives no harness journal, receipt, projection, or current-index credential.
Its only writable storage capability targets its unique run-local role root.
The harness owns all copying, content addressing, handoff materialization,
submission assembly, and publication.

This broker contract is the portable boundary across platforms. It must deny an
unknown, expired, cross-run, cross-stage, wrong-operation, or overused
capability before resolving an artifact.

### 4.3 Process boundary

Prompt wording is not an access boundary. The version 1 Linux executor runs each
CLI-capable role in a separate rootless OCI container. The container uses private
user, process, and mount namespaces; a read-only root filesystem; no Linux
capabilities; `no_new_privileges`; and the pinned seccomp policy in its immutable
executor-profile artifact. The only writable mount is the exact role root. Pinned
runtime resources are read-only, and the capability broker is reached through one
private Unix socket. Project storage, formal storage, other role roots, host
credentials, and the host process namespace are never mounted.

Network egress is either absent or forced through the broker-managed allowlist
proxy named by the frozen capability grant. Direct container egress is denied.
Every `RoleInvocationStart` binds the exact OCI image-manifest digest and executor
profile artifact used for that process. A mismatch blocks the start.

Linux release tests must attempt path traversal, symlink escape, mount escape,
environment-secret read, process inspection, undeclared network access, direct
project-store access, and cross-role workspace access. Windows and other
platforms remain unsupported until an executor profile passes the same tests. An
executor without the rootless OCI boundary is allowed only when its callable
interfaces cannot access the host filesystem, network, environment, process
table, command line, or external storage.

## 5. Context assembly

The harness builds a role-specific context packet from only the items authorized
by that role's frozen read allowlist, in this scientific order:

1. system invariants and the active phase contract;
2. the resolved user command and scope;
3. the exact current formal records required by the phase;
4. role-specific structured summaries and current attention items;
5. user-selected optional context and exact selected history;
6. accepted handoffs from earlier roles in the same run;
7. on-demand references to permitted primary artifacts;
8. the frozen role profile, skills, tools, and knowledge resources.

These numbers are the context-class ranks used by the packing policy. The
special `review_packet` class has rank 9 and is used only for the outside
reviewer, whose scientific context contains no other class.

This sequence is not a grant of access. An item is excluded when the frozen
allowlist does not authorize it. Authorization is resolved before capacity
packing. An unselected or unauthorized item never enters the candidate set.

Each packet records artifact identities and digests. The sealed run manifest
also binds every contract-selected input and expected output to its exact
executable-contract ID. A prepared context additionally records the formal
inputs and user choices from which the harness constructed it.

The normal context is current and lean. Historical runs are excluded unless the
user selects them or the phase contract names a specific historical object. A
role may inspect a permitted primary artifact when a summary is insufficient,
but the material conclusion must be returned through a structured statement,
evidence item, issue, or handoff.

### 5.1 Capacity declaration

Before packing, the harness freezes:

- exact model identity;
- tokenizer identity, version, artifact, and digest;
- model context-window capacity;
- reserved output and runtime tokens;
- usable input-token budget;
- independent input-byte budget;
- context-packing policy identity, version, artifact, and digest.

The usable token capacity is

\[
C_{\mathrm{input}} = C_{\mathrm{window}}
  - C_{\mathrm{output}}
  - C_{\mathrm{runtime}}.
\]

The harness rejects a declaration when the recorded usable capacity does not
equal this value. Token counts use the frozen tokenizer. Byte counts use the
exact rendered bytes. Both limits must hold.

### 5.2 Deterministic packing

The harness constructs and freezes an ordered candidate manifest. Each item has
an immutable artifact identity, context class, requirement, numeric priority,
contract order, purpose, deterministic size estimate, and permitted representation.
Estimates support diagnostics only; exact rendered counts decide admission.

Packing follows this algorithm:

1. Validate and admit every `required` and `user_selected` item before optional
   items.
2. If these items exceed either budget, fail preparation unless the bound policy
   explicitly permits frozen compaction for the affected item.
3. A frozen compaction is a new immutable artifact. It binds every source
   artifact, the compaction contract, generated content, and digest. The source
   is never overwritten or silently shortened.
4. Consider optional items by ascending numeric priority. Break ties by context
   class, contract order, and item ID.
5. For each optional item, tentatively render the complete admitted context plus
   that item with the frozen renderer and tokenizer. Admit it only when the exact
   total satisfies both budgets. Otherwise omit it whole and record its source,
   deterministic estimate, and capacity reason.
6. Order admitted items by context class, contract order, and item ID. Render
   one immutable context artifact and count its exact tokens and bytes. Any count
   mismatch or budget excess fails preparation.

An item cannot be sliced, summarized, or dropped without a corresponding frozen
compaction or omission record. A failed preparation produces an explicit
capacity diagnostic and never enters `RUNNING`.

### 5.3 Prepared context and closed snapshot

The nested prepared context is sealed before role execution. Its digest is the
SHA-256 digest of RFC 8785 canonical JSON over an object containing exactly:
`phase_contract`, `role_profile`, `model_capacity`, `packing_policy`,
`preference_memory_binding`, and `prepared_context`. The run role step binds
this `prepared_context_sha256` before the role starts.

The prepared context records the exact rendered input artifact, ordered context
items, explicit optional omissions, on-demand read capabilities, preference
memory version, budgets, counts, packing outcome, and preparation time. A
mutable current pointer, folder scan, unindexed transcript, or unstated agent
memory is not a valid scientific input.

The broker records every successful on-demand read as an immutable event with a
monotone sequence, exact capability, artifact pointer and digest, token and byte
counts, time, prior event digest, and event digest. Event digests use RFC 8785
canonical JSON with `event_sha256` omitted. The first event uses 64 zeroes as
its prior digest. The final ledger head equals the last event digest, or 64
zeroes when no read occurred.

The prepared context records the token and byte capacity remaining after its
exact rendered input. Before an on-demand read, the broker counts the complete
immutable artifact with the frozen tokenizer and checks its capability limits
and the cumulative remaining budgets. It supplies the whole artifact or refuses
the read. It never clips the artifact. A refusal supplies no content, creates no
scientific-input event, and returns a stable broker denial code to the harness.
Persistent platform security telemetry is deployment policy, not a research
authority record.

At role closure, the harness seals the prepared context and the ordered access
ledger as a `RoleContextSnapshot`. `snapshot_sha256` is the SHA-256 digest of
the RFC 8785 canonical full snapshot with only `snapshot_sha256` omitted. The
prepared context does not change when ledger events are added. Reproducibility
means that the exact supplied and read artifacts can be reconstructed. It does
not mean that a stochastic model must generate identical output.

### 5.4 Outside-reviewer closure

For the Phase 5 outside reviewer, `p5.review_packet` is the only scientific
context item. Project preference memory is disabled. The on-demand capability
list and access ledger are empty. No project formal record, attention item,
selected history, user command detail, internal specialist artifact, project
memory, or project-specific knowledge resource is otherwise supplied.

Hermes assignee profiles may retain persistent memory across tasks. The outside
reviewer therefore uses a profile distinct from the research lead, theorist, and
data analyst. Authoring roles may share a profile with one another. This distinct
profile prevents direct sharing of author-role memory, but it does not establish
that persistent reviewer-profile memory is empty. The current Hermes integration
cannot attest that condition. Distinct assignment is the current fail-closed
minimum. Full closed-packet enforcement requires an executor capability for an
ephemeral or no-memory reviewer session, or a verified memory reset.

Configuration projections bind each target assignment and skill action to the
complete four-role mapping state and observed local resource state. A legacy
conflicting assignment remains visible with nonconflicting repair choices, but
skill installation is disabled and run preparation rejects the mapping until it
is repaired.

Execution metadata is a closed allowlist containing only run, phase, mode,
stage, execution-group, and role identifiers; phase-contract and reviewer-profile
artifact pointers; model and tokenizer identities; token and byte budgets;
output-contract pointers; role-local write root; network and wall-time limits;
and explicit false values for project-storage and formal-storage credential
exposure. The schema rejects every other metadata field. System invariants and
the non-project reviewer profile are bound through the declared phase-contract
and role-profile artifacts, not through an open metadata map.

## 6. Instruction precedence

When instructions conflict, apply this order:

1. system invariants, safety, and access boundaries;
2. the versioned phase contract;
3. the resolved user command within that contract;
4. the role profile and phase instruction;
5. suggestions contained in scientific context.

Scientific evidence does not become weaker because it appears lower in this
instruction order. The order governs actions and scope, not the weight of
evidence. A role must report a scientific conflict rather than following a
lower-level instruction that would conceal it.

## 7. Memory policy

The system distinguishes three kinds of memory.

### 7.1 Run working memory

Run working memory supports reasoning inside one role workspace. It is
diagnostic, run-local, and not a future scientific dependency unless material
content is promoted through a structured output.

### 7.2 Project preference memory

Project preference memory may record stable user choices such as notation,
target audience, biological terminology, computing constraints, or preferred
reporting conventions. It is versioned, visible to the user, and frozen when
used. The role context records the exact memory ID, version, artifact, and
digest, or records that preference memory is disabled. It cannot change phase
scope, method identity, access authority, or scientific outcome.

### 7.3 Scientific project memory

Persistent scientific knowledge consists of formal project records, statements,
evidence, attention items, decisions, and handoffs. Free-form chat history and
private agent memory are not substitutes for this record.

No role may silently summarize old runs into persistent memory. A proposed
scientific memory change must pass through the phase submission and promotion
contract.

## 8. Skills, tools, and knowledge resources

A skill provides a method of working, not scientific authority. The profile
manifest names each required skill by stable package identity, version, and
digest. Preparation fails with a precise message when a required skill is
missing. Optional skills are exposed to the user and recorded when selected.

Knowledge resources may include literature indexes, mathematical libraries such
as Mathlib, benchmark collections, optimization problem libraries, biological
ontologies, or approved data catalogs. Each adapter records:

- resource and version;
- query or theorem identifier;
- retrieved item identity;
- retrieval time;
- license or access restriction;
- how the item entered a statement, proof, computation, or decision.

Retrieved content cannot support a formal material claim without provenance.
A library theorem reference does not prove that the role applied it correctly.

Tools are least-privilege capabilities. The profile lists read scope, write
scope, network scope, execution limits, and secret references. A tool request
still passes through the capability broker and, when applicable, the process
sandbox. Profile text cannot expand a frozen capability.

## 9. Communication between roles

Roles communicate through immutable artifacts and structured handoffs. The producing role writes the handoff inside its role root. After closure, the harness verifies its schema and digest and materializes an immutable shared reference for permitted consumers. A handoff states:

- work completed and material changes;
- exact statements and evidence addressed;
- assumptions and limitations;
- unresolved issues with stable IDs and severity;
- what the next role must verify;
- links to detailed artifacts.

The phase contract controls visibility:

- Phase 1 discovery roles work independently before lead synthesis.
- Phase 2 proposal roles work independently, then exchange explicit
  cross-reviews before lead synthesis.
- Phase 3 proceeds theorist, data analyst, then research lead.
- Phase 4 proceeds data analyst, theorist, then research lead.
- Phase 5 review-revision gives the three parallel roles one frozen manuscript
  snapshot but distinct read allowlists. The theorist receives the mathematical
  internal set, the data analyst receives the empirical internal set, and the
  outside reviewer receives only `p5.review_packet`. The lead receives all fixed
  reports only in the later revision stage.

This provides round-robin scientific awareness without accumulating an
unbounded conversation. A later stage in the same run receives its accepted
handoffs. A later run receives the current formal result and only the handoffs
that a phase contract has explicitly promoted or selected, not every prior
exchange.

## 10. Lead synthesis contract

At the end of each phase run, the research lead produces a structured scientific
record and compact decision brief. The brief must state:

1. the current decision available to the user;
2. the most defensible conclusion;
3. the fundamental methodological or scientific contribution;
4. the material change from the prior current record;
5. the strongest evidence and counterevidence;
6. the main assumption, uncertainty, and unresolved disagreement;
7. the smallest next result that would change the decision;
8. the available user-controlled actions and their consequences.

The language should be compact, direct, and familiar to statistical,
mathematical, computational, and biological researchers. A summary must not
replace the proof, code, evidence, or manuscript it cites.

## 11. Validation requirements

The harness validates that:

- every role plan names an exact stage-compatible profile manifest;
- required output contracts, skills, tools, and knowledge adapters are present
  and match immutable versions and digests;
- each context item is authorized, frozen, and assigned a purpose;
- the prepared-context and final snapshot digests match their exact RFC 8785
  digest views;
- the final snapshot reproduces the exact `PreparedRoleContext` and cites its
  identity, artifact, whole-record digest, and projection digest;
- every `RoleInvocationStart` copies the complete sealed role-plan entry and
  resolves actual inputs, output contracts, capabilities, profile, and write root;
- every successful `RoleInvocationClosure` covers all required outputs, and a
  downstream start binds only its accepted immutable artifacts;
- model capacity, tokenizer identity, token counts, byte counts, priority order,
  omissions, and compactions match the frozen packing policy;
- selected history matches the user's command;
- each role step freezes the exact stage ID, execution group, input allowlist,
  output IDs, and unique role-specific write root required by the phase contract;
- every on-demand read names an unexpired stage-bound capability, matches its
  immutable artifact and digest, respects its use limit, and appears in the
  ordered hash-chained access ledger;
- initial context plus all successful on-demand reads stays within the frozen
  token and byte budgets;
- completed role workspaces become immutable before later roles read them;
- every required shared handoff resolves to a verified source artifact under
  the producing role root with the same digest;
- the outside reviewer received only `p5.review_packet` as scientific context
  and no project-specific memory, knowledge resource, selected history,
  attention item, or command detail outside it, while the theorist and data
  analyst received exactly their declared role-specific read sets;
- outside-reviewer execution metadata contains only the closed schema allowlist;
- the role process received no project-store, formal-store, journal, receipt,
  projection, or current-index credential;
- the lead disposed or preserved every material role issue;
- no formal output depends only on an unindexed transcript or hidden memory.

These checks implement the role-context and role-isolation requirements MH-53
and MH-54.

These checks establish reproducibility and communication discipline. They do not
establish that the role's scientific reasoning is correct.

## 12. Researcher-facing configuration

The configuration UI shows, for each role and phase:

- active profile version;
- scientific stance summary;
- required and installed skills;
- optional knowledge resources;
- tool permissions;
- memory policy;
- model capacity, current context use, explicit omissions, and frozen
  compactions;
- project-specific customizations.

A user may create a project-specific profile version. The interface validates it
before use, shows which default was changed, and warns when a required scientific
or operational capability is missing. Customization never grants direct formal
record access.

## 13. Acceptance criteria

Implementation must prove that:

1. two runs with the same frozen profile, prepared contexts, and input allowlists identify the same role inputs even if current project records later change;
2. a missing required skill blocks preparation with the affected role and phase;
3. unselected history and hidden conversation memory are absent from a role
   packet;
4. a completed role artifact cannot be rewritten by a later role;
5. P3 and P4 enforce their fixed role orders and handoffs;
6. the Phase 5 reviewer can resolve only `p5.review_packet` as scientific context and cannot resolve internal formal records, specialist artifacts, project memory, project-specific knowledge resources, selected history, or attention items;
7. a retrieved theorem, paper, dataset, or library object retains provenance;
8. a profile change creates a new version without altering earlier runs;
9. role disagreement remains visible in the lead decision brief;
10. the Web UI and remote client use the same frozen role-profile contract;
11. every role profile is rejected outside its declared `applicable_stage_ids`;
12. unlisted reads and writes outside the role-specific run root are denied at
    the harness boundary;
13. every harness-owned handoff or submission component resolves to one verified
    immutable source under a producing role root with the same digest;
14. exact-fit context passes, optional capacity omissions are visible, permitted
    compactions are immutable, and oversized required context otherwise blocks
    preparation;
15. the same candidate set, model, tokenizer, budgets, and policy produce the
    same ordered prepared-context manifest and digest;
16. every successful on-demand read replays from the broker ledger, and a
    missing, reordered, or altered event changes or invalidates its head digest;
17. Linux tests deny path, symlink, mount, process, environment-secret, network,
    direct-storage, and cross-role escapes for every CLI-capable role;
18. the outside reviewer is rejected when given preference memory, an on-demand
    capability, an internal scientific item, or execution metadata outside the
    closed allowlist;
19. the exact supplied and read inputs remain reconstructable without claiming
    deterministic model output;
20. an on-demand artifact that exceeds its capability limit or remaining
    capacity is refused whole and creates no scientific-input ledger event.
21. changing an accepted upstream artifact or closure digest rejects a downstream
    role start;
22. a failed, cancelled, missing, duplicated, or reordered role closure prevents
    creation of `RunSubmission`;
23. a valid `RunSubmission` covers the complete selected role plan, binds the
    final lead closure, and includes every required accepted output;
24. a reviewer-author profile collision is visible and repairable in
    configuration, cannot install role skills, and is rejected before any run
    manifest or role invocation is created;
25. the harness supplies only `p5.review_packet` as reviewer project context,
    and the execution record must attest an ephemeral or no-memory session or a
    verified reset before the system claims that reviewer memory was empty.
