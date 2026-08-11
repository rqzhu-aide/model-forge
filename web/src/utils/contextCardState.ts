/**
 * Reusable context-card selection state logic.
 *
 * Shared across all phase tabs (P2, P3, P4, P5) so the checkbox
 * behaviour is identical everywhere.
 *
 * Rules:
 *  - Required context (presence "always"): locked + checked.
 *    The checkbox is grayed out and cannot be toggled.
 *  - Optional context that EXISTS (e.g. P3/P4/P5 downstream results):
 *    checked by default, NOT grayed out. The user can uncheck.
 *  - Optional context that DOES NOT EXIST: grayed out + unchecked.
 */
export interface CardState {
  /** Whether the checkbox should be checked. */
  checked: boolean;
  /** Whether the checkbox is disabled (locked). */
  locked: boolean;
  /** Whether the underlying record is missing (unavailable). */
  unavailable: boolean;
}

interface CardStateInput {
  /** At least one option in the group is contract-required (locked). */
  required: boolean;
  /** At least one option in the group has a real record (exists). */
  exists: boolean;
  /** All options in the group are currently selected. */
  allSelected: boolean;
}

/**
 * Derive the display state of a context card from its options.
 *
 * Pass the result of {@link summariseGroup} as input.
 */
export function deriveCardState(input: CardStateInput): CardState {
  // Required (always-present): locked + checked, never toggleable.
  if (input.required) {
    return { checked: true, locked: true, unavailable: false };
  }

  // Optional but the record doesn't exist: disabled + unchecked.
  if (!input.exists) {
    return { checked: false, locked: true, unavailable: true };
  }

  // Optional and exists: toggleable, default checked.
  return { checked: input.allSelected, locked: false, unavailable: false };
}

export interface CardStateOption {
  required: boolean;
  /** True when the record exists (not marked disabled/missing). */
  disabled?: boolean | undefined;
  selected: boolean;
}

/**
 * Summarise a list of card options into the input needed by
 * {@link deriveCardState}.
 *
 * Works for both single-option and multi-option groups.
 */
export function summariseGroup(
  options: CardStateOption[],
): CardStateInput {
  return {
    required: options.some((o) => o.required),
    exists: options.some((o) => !o.disabled),
    allSelected: options.every((o) => o.selected),
  };
}
