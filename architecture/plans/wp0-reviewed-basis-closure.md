# WP0: Reviewed-Basis Closure - Implementation Scope

Status: Partially implemented (audited 2026-08-03). The exit gate remains open.

## Implementation audit

Implemented foundations:

- new commands can carry the phase descriptor basis in `sealed_basis`;
- the command digest covers the embedded basis;
- the API exposes the descriptor basis;
- preparation performs an initial authority, input-generation, and bundled
  role-resource comparison;
- stable stale-basis errors and basic tests exist.

The implementation is not complete because:

- phase-role resolution is attempted with empty choices, so method-bound modes
  can silently omit all role resources;
- the schema permits an underspecified basis and new preparation still accepts
  a missing seal;
- missing inputs, missing live roles, unmatched input entries, method changes,
  and several digest changes can pass without rejection;
- the resource snapshot represents bundled recommendations rather than the
  exact installed Hermes profile, model/provider configuration, phase
  instruction, tools, knowledge resources, and memory policy;
- the researcher cannot yet inspect the complete basis in the Web interface.

Do not treat the current `sealed_basis` object as proof of exact reproducibility
or enable publishable Hermes execution from it. The original design below
remains useful, but any status statement inside it is subordinate to this
audit and to the Exit Gate.

## Revision 1 changelog

Reviewed against the current source. The compare-and-seal design is sound and
all original code citations verified within ±1 line. Corrections:

1. **C1 - Profile and role-resource sealing added (was missing).** The
   original draft sealed inputs, authority head, and method identity, but its
   own test case 7 (profile drift) was unimplementable and WP0 acceptance
   tests 4-5 in
   [10-open-implementation-gaps.md](../10-open-implementation-gaps.md) require
   rejecting profile, soul, skill, tool, and knowledge-resource drift. Without
   this, WP0 is not closed. Section "Proposed Fix" now includes role
   resources.
2. **C2 - Schema compatibility rule added.** `_prepare` revalidates every
   stored sealed command against `run-command.schema.json`
   (`run_coordinator.py:174`). A **required** new `sealed_basis` field would
   break restart recovery for every run sealed before the upgrade. The field
   must be optional at the schema level and enforced in code for new commands,
   with an explicit legacy fallback.
3. **C3 - Error taxonomy aligned.** Drift between view and submit is already
   rejected by the existing descriptor check with `CONTROL_HEAD_STALE`
   (`service.py:568-576`). The new code covers drift between acceptance and
   preparation and needs a new stable error registered in the error model,
   carrying the drifted category (the gaps doc requires identifying which
   category changed). Original test case 1 mislabeled the rejecting mechanism.
4. **C4 - Gap diagram corrected.** The view→submit window is already closed by
   the descriptor recompute-and-match at acceptance. The real open window is
   acceptance→preparation, which is asynchronous (`asyncio.create_task`,
   `service.py:743`).
5. **C5 - Files-to-change list completed.** Added the digest contract,
   architecture examples and negative fixtures, traceability, scenarios, and
   the error model, per WP0 deliverable 7 ("update schemas, examples, invalid
   fixtures, digest contracts, traceability, and scenarios together").
6. **C6 - Scope statement added.** This document is one slice of WP0. The
   remaining WP0 deliverables (missing normative representations, reviewer
   no-memory attestation, withdrawal decision) are listed so this plan is not
   read as closing all of WP0.

## Historical problem statement before the initial implementation

The Operational Completion Plan (section 5, WP0) requires that the user's
accepted command correspond to one exact reviewed scientific basis, sealed
atomically. Currently there is a **time-of-check to time-of-use gap** between:

1. **Phase view rendered** → action descriptor computed (includes current input
   digests and authority head)
2. **User reviews and submits** → command sealed (phase contract digest, choices)
3. **Preparation runs** → inputs re-resolved, manifest frozen (input generations,
   profiles, resources, publication basis all re-read from live state)

Window 1→2 is **already closed**: `start_run` recomputes the phase view fresh
and requires the submitted `action_descriptor_id` to match the current one
(`service.py:558-576`), and the descriptor basis already hashes the authority
head, current-input artifact digests, and method identity.

Window 2→3 is **open**: preparation runs asynchronously after acceptance
(`service.py:742-745`), and nothing in the sealed command records the reviewed
basis. Between acceptance and preparation, any formal state change (new
publication by a concurrent run, profile reassignment, method lifecycle
change, authority root update) silently shifts the basis. The system has
*partial* guards but no atomic seal.

## Historical baseline before the initial implementation

This section describes the source state used to design the first implementation
in commit `fb326de`. It is retained as rationale and must not be read as the
current audited state.

### Action descriptor (step 1)

`projections/phase_configuration.py:87-109` builds `descriptor_basis`, which
includes:

- project_id, phase, mode, phase_contract_version, phase_contract_sha256
- method_identity (stable_id, version, definition_sha256 -
  `MethodIdentity.to_dict`, `identities.py:216-221`)
- reviewed_current_inputs with option_id + artifact_id + sha256 per option
  (**no generation_id**)
- authority_head (authority_sequence, authority_root_sha256, current_revision)

This is hashed into the `descriptor_id` (`phase_configuration.py:19-26`). The
`start_run` handler (`service.py:558-568`) recomputes the phase view fresh and
rejects a mismatched descriptor with `CONTROL_HEAD_STALE`.

The descriptor basis contains **no profile or role-resource information**, so
the researcher does not review - and the command cannot seal - which profile,
soul, or skill bundle each role will use.

### Run command (step 2)

`harness/commands.py:build_run_command` seals:

- phase_contract_version, phase_contract_sha256
- mode, choice_values, context_policy
- selected_current_input_ids (option IDs only - **not** their generations or
  digests)
- resource_constraints
- **Missing:** no input generation IDs or digests, no method digest, no
  authority head binding, no profile/role-resource identities

The command content digest (`run_command.content`,
`architecture/contracts/digest-contracts.json`) covers the whole document
except `/content_sha256`, so any added field is automatically digest-bound -
but the digest contract, schema, examples, and fixtures must still be updated
together.

### Preparation (step 3)

`run_coordinator.py:_prepare` (line 160) re-resolves everything from live
state:

- Inputs: `resolve_run_inputs` re-reads current records (line 191)
- Profiles: `_freeze_role_resources` reads live profile assignments and role
  resources - profile name, profile_version, soul_sha256, and per-skill
  bundle_sha256 are captured here (lines 523-568), but only at preparation
  time and never compared to a reviewed basis
- Publication basis: `capture_publication_basis` captures authority head
  (line 212)
- Method: `_selected_method` re-reads from choice_values (line 211)

`_verify_frozen_inputs` (lines 570-594) then checks the authority head and
input generations against live state and raises `RepositoryConflictError` on
mismatch. This detects drift **during** preparation only (the window between
capture at line 212 and verification at line 230). It cannot detect drift
between acceptance and preparation, because the prepared values are themselves
read from the drifted state.

## Original gap

```
Phase View ══[closed: descriptor recompute + match]══ Command Accept ══[OPEN: async, basis unsealed]══ Preparation
```

| What | Sealed at acceptance? | Drift window | Risk |
|---|---|---|---|
| Input generation IDs + digests | No (descriptor only, not command) | accept→prepare | **HIGH** - concurrent publication replaces current records |
| Method identity (version + definition digest) | No (descriptor only) | accept→prepare | **MEDIUM** - method lifecycle change between accept and prepare |
| Profile assignment + soul/skill digests | Not reviewed, not sealed | view→prepare (entire span) | **HIGH** - profile reassigned at any time; never detected |
| Authority head | No (descriptor only) | accept→prepare | **MEDIUM** - new authority event between accept and prepare |
| Phase contract | Yes (command + descriptor) | - | **LOW** - already double-checked (`run_coordinator.py:177-182`) |

## Original proposed fix: seal basis in the command

### Approach: "Compare-and-Seal" at command acceptance

When the user submits `start_run`, the handler should:

1. **Re-derive the action descriptor** (already done - `service.py:558-568`)
2. **Verify the descriptor_id matches** what the user saw (already done -
   rejects with `CONTROL_HEAD_STALE`)
3. **Extract the sealed basis from the matched descriptor** (NEW - read the
   `reviewed_current_inputs` digests, `authority_head`, `method_identity`, and
   the new `role_resources` from the descriptor basis that was matched; since
   the descriptor was recomputed from live state and matched, this basis is
   live-true at acceptance)
4. **Bind the sealed basis into the RunCommand** (NEW - add an optional
   `sealed_basis` field to the command document)
5. **At preparation time, verify live state against the command-sealed
   basis** (ENHANCED - `_verify_frozen_inputs` compares against the sealed
   values, rejecting with a category-identifying stale-basis error before any
   manifest is frozen)

### Concrete Changes

#### 1. Extend `run-command.schema.json`

Add an **optional** `sealed_basis` object (C2 - optional so stored pre-upgrade
commands still validate during recovery):

```json
{
  "sealed_basis": {
    "type": "object",
    "additionalProperties": false,
    "required": [
      "authority_sequence",
      "authority_root_sha256",
      "current_revision",
      "frozen_input_generations",
      "role_resources"
    ],
    "properties": {
      "authority_sequence": { "type": "integer", "minimum": 0 },
      "authority_root_sha256": { "$ref": "common-definitions.schema.json#/$defs/sha256" },
      "current_revision": { "type": "integer", "minimum": 0 },
      "frozen_input_generations": {
        "type": "array",
        "items": {
          "type": "object",
          "additionalProperties": false,
          "required": ["option_id", "generation_id", "sha256"],
          "properties": {
            "option_id": { "type": "string" },
            "generation_id": { "type": "string" },
            "sha256": { "$ref": "common-definitions.schema.json#/$defs/sha256" }
          }
        }
      },
      "method_identity": {
        "type": ["object", "null"],
        "additionalProperties": false,
        "required": ["stable_id", "version", "definition_sha256"],
        "properties": {
          "stable_id": { "type": "string" },
          "version": { "type": "integer", "minimum": 1 },
          "definition_sha256": { "$ref": "common-definitions.schema.json#/$defs/sha256" }
        }
      },
      "role_resources": {
        "type": "object",
        "additionalProperties": false,
        "patternProperties": {
          "^[a-z_]+$": {
            "type": "object",
            "additionalProperties": false,
            "required": ["profile", "profile_version", "soul_sha256", "skills"],
            "properties": {
              "profile": { "type": "string" },
              "profile_version": { "type": "string" },
              "soul_sha256": { "$ref": "common-definitions.schema.json#/$defs/sha256" },
              "skills": {
                "type": "array",
                "items": {
                  "type": "object",
                  "additionalProperties": false,
                  "required": ["skill_id", "source_revision", "bundle_sha256"],
                  "properties": {
                    "skill_id": { "type": "string" },
                    "source_revision": { "type": "string" },
                    "bundle_sha256": { "$ref": "common-definitions.schema.json#/$defs/sha256" }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

(Validate `common-definitions.schema.json#/$defs/sha256` is the correct ref
target before editing; mirror the exact shape `_freeze_role_resources`
produces at `run_coordinator.py:561-567`.)

#### 2. Surface the sealed basis in `descriptor_basis` (`phase_configuration.py`)

- Add `generation_id` to each entry of `reviewed_current_inputs` (available
  from the current-slot records the service already loads; used later as
  `frozen_basis` identity, `run_coordinator.py:238`).
- Add a `role_resources` section per required role: profile, profile_version,
  soul_sha256, and skill bundle digests. This also gives the researcher a
  pre-launch view of profile/resource versions, which WP3 requires anyway -
  build it here once and let WP3 render it.

#### 3. Modify `build_run_command` (`harness/commands.py`)

Accept the sealed basis and embed it in the command document. Because the
`run_command.content` digest contract hashes the whole document except
`/content_sha256`, the sealed basis is automatically digest-bound. Enforce in
code that **new** commands always carry `sealed_basis` (the schema keeps it
optional only for stored pre-upgrade commands).

#### 4. Modify `service.py:start_run` (lines 539-746)

After the descriptor match, extract the basis from the matched descriptor and
pass it to `build_run_command`. The idempotent-replay path (lines 548-554)
returns before the descriptor check and must keep doing so - a replay returns
the original sealed basis and never re-resolves (gaps-doc acceptance test 7).

#### 5. Enhance `_verify_frozen_inputs` (`run_coordinator.py:570`)

- If the command carries `sealed_basis`: before freezing the manifest, verify
  every sealed value against live state - input generation IDs and digests,
  authority head triple, method version + definition digest, and per-role
  profile/soul/skill identities. Reject on the first mismatch with a new
  stable error (below) naming the drifted category.
- If the command has no `sealed_basis` (sealed before this change): fall back
  to the current post-hoc check. Acceptable because the baseline is
  greenfield; must be logged as a legacy-basis preparation and documented.

#### 6. Register the new stable error

Add a `STALE_BASIS` (or similarly named) stable error to the command/run error
model with a required `category` detail field (`formal_input`,
`authority_head`, `method`, `profile`, `skill`, `knowledge_resource`). The
gaps doc requires the rejection to identify which category changed. Do not
reuse `CONTROL_HEAD_STALE` - that code means "the displayed descriptor is no
longer current at submit" and stays as-is.

## Files to Change

| File | Change |
|---|---|
| `architecture/schemas/run-command.schema.json` | Add optional `sealed_basis` object |
| `architecture/contracts/digest-contracts.json` | Confirm `run_command.content` coverage; update documented field inventory |
| `architecture/examples/` + invalid fixtures | New positive example with `sealed_basis`; negative fixtures (bad digest, missing category field) |
| `architecture/07-contract-traceability.md` + affected scenarios | Register the new sealed-basis guarantee |
| `src/method_hub/projections/phase_configuration.py` | Add `generation_id` and `role_resources` to `descriptor_basis` |
| `src/method_hub/harness/commands.py` | Accept and embed sealed basis; require it for new commands |
| `src/method_hub/application/service.py` | Extract basis from matched descriptor; pass to command builder |
| `src/method_hub/application/run_coordinator.py` | Verify sealed basis at preparation; legacy fallback path |
| error model (`src/method_hub/errors.py` / API error definitions) | Register `STALE_BASIS` with category detail |
| `tests/test_*.py` | New tests below; update schema-round-trip and recovery tests |

## Test Cases

1. **Stale input at submit**: current record republished between view and
   submit → rejected by the **existing** descriptor check with
   `CONTROL_HEAD_STALE` (mechanism corrected in C3).
2. **Stale authority at submit**: authority root changes between view and
   submit → same existing rejection.
3. **Drift between accept and prepare (input)**: a concurrent publication
   lands after acceptance but before preparation → preparation rejects with
   `STALE_BASIS` / category `formal_input`; no manifest frozen; no role
   starts; no formal generation, authority event, or current-index change.
4. **Drift between accept and prepare (method)**: method lifecycle advances
   the definition after acceptance → `STALE_BASIS` / category `method`.
5. **Drift between accept and prepare (profile/resources)**: profile
   reassignment or skill-bundle change after acceptance → `STALE_BASIS` /
   category `profile` or `skill`. (Requires C1; this was the original draft's
   test 7 and is only implementable with role-resource sealing.)
6. **No drift**: sealed basis matches live state at preparation → run proceeds
   normally; manifest inputs, method identity, profiles, and resources exactly
   equal the accepted basis by identity, version, generation, and digest
   (gaps-doc acceptance test 1).
7. **Idempotent replay**: same command submitted twice → original run returned
   with its original sealed basis; no re-resolution (gaps-doc acceptance
   test 7).
8. **Legacy command**: a stored pre-upgrade command without `sealed_basis`
   still passes preparation validation and recovery (C2).
9. **Rejection cleanliness**: every rejected drift leaves formal research
   state unchanged and produces one attributable operational audit entry
   (gaps-doc acceptance test 8).

## Remaining WP0 Work Outside This Document

After the implementation audit above, this plan does not yet close the
reviewed-basis gap. WP0 also requires, per the
Operational Completion Plan section 5:

- the missing normative representations: orchestration binding, role execution
  record, progress event, state-specific RunState requirements, and the
  dedicated Phase 4 evidence-index / empirical-synthesis / implementation /
  phase-decision record obligations;
- the executor attestation proving the outside reviewer ran in an ephemeral or
  verified no-memory session;
- the decision whether formal-generation withdrawal is in version 1.

Those need their own scoping documents before WP0 can be called complete.

## Exit Gate

A developer can start from the user-reviewed screen and name every exact
object - formal inputs, method identity, authority head, and every role's
profile, soul, and skill bundle - that will appear in the manifest before any
role starts. Any drift rejects the command or fails preparation closed,
identifying the drifted category, without scientific side effects.
