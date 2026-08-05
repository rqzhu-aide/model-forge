# Open Structural Implementation Gaps

## Status

The reviewed-basis gap in this file is CLOSED: WP0 (reviewed-basis closure)
sealed the accepted command basis, and WP-H1 added the sealed-basis
acceptance-time completeness gate. The reviewer-memory boundary below remains
open. The full production sequence is maintained in the
[Trusted Local Execution Program](plans/trusted-local-execution-program.md).

## Current gap

The accepted `RunCommand` records phase, mode, contract identity,
`choice_values`, and `selected_current_input_ids`. A method-bound command already
records an exact method identity in its phase choice. The command does not,
however, seal the exact current generations and digests behind those input IDs,
or the exact role profiles and their soul, skill, tool, knowledge-resource, and
memory-policy identities. Those objects are resolved later during `preparing`.

This creates a drift window. A researcher may review current records and role
resources as one displayed basis, accept the command, and receive a manifest
prepared after one of those records or resources has changed. The resulting
manifest may be internally reproducible but differ from the basis the researcher
reviewed. A UI display, timestamp, or cached option list is not an authority
binding and cannot close this window.

## Required architecture closure

The harness must adopt one of these two integrity-equivalent boundaries:

1. **Command-sealed basis.** The accepted command seals the reviewed current-index
   authority head; exact formal input generation IDs and artifact pointers with
   digests; exact method identity and method-record generation; and each role's
   exact profile artifact, including its soul, instructions, memory policy,
   required or selected skills, tools, and knowledge resources. Preparation must
   reproduce exactly those identities and must not substitute a newer current
   record, profile, or resource.
2. **Atomic acceptance and preparation.** The command binds the authority and
   role-resource basis reviewed by the user. Command acceptance, exact input and
   resource resolution, and manifest sealing occur as one compare-and-seal
   operation against that basis. Any head or resource-digest change aborts the
   whole operation, so no accepted run exists with an unresolved scientific
   basis.

Either boundary must preserve an exact command-to-manifest correspondence. The
manifest may add execution details, but every scientific input and role resource
must be the object authorized at acceptance.

## Rejection behavior

The harness must fail closed when a reviewed input generation, authority head,
method identity, role profile or soul, required skill, or other bound role
resource changes or cannot be resolved at the sealing boundary.

- Return a stable stale-basis or unavailable-resource conflict that identifies
  which category changed.
- Do not substitute the latest object, start a role, or create a manifest with a
  different basis.
- Do not create a formal generation, authority event, publication receipt, or
  current-index change. The operational command audit may record the rejected
  attempt.
- Require the researcher to refresh the displayed basis, review the change, and
  issue a new command.
- An idempotent replay of an accepted command must return its original sealed
  basis and must never resolve newer current objects.

## Acceptance tests

1. With no concurrent change, every frozen manifest input, method identity,
   profile, soul, and required or selected resource exactly matches the accepted
   basis by identity, version, generation when applicable, and digest.
2. If a selected current input changes after UI review but before sealing, the
   command is rejected and no role starts.
3. If the method record changes while the stable method ID remains the same, the
   exact version and definition digest comparison rejects the stale basis.
4. If a role profile changes its soul, instruction, memory policy, or output
   obligation, preparation does not silently use the new profile.
5. If a required or selected skill, tool, or knowledge resource changes version
   or digest, or becomes unavailable, preparation is rejected without fallback.
6. Under command-sealed resolution, each exact pointer must remain current and
   eligible. Under atomic resolution, any mismatch with the reviewed authority
   or resource basis aborts acceptance and preparation together.
7. Replaying the same idempotency key cannot produce a manifest with a different
   input or role-resource basis.
8. Every rejected race leaves formal research state unchanged and produces a
   stable, attributable operational audit result.

## Reviewer-memory boundary

Sealing the outside reviewer's packet, profile, and skills does not prove that a
persistent agent profile has empty memory. As stated in
[Outside-reviewer closure](08-role-context-and-communication.md#54-outside-reviewer-closure),
a profile distinct from all authoring roles is the minimum isolation condition.
The system may claim full closed-packet review only when execution also attests
an ephemeral or no-memory session, or a verified memory reset.
