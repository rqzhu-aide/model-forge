import { describe, expect, it } from "vitest";
import type { ActionDescriptor } from "../api/types";
import { actionConfirmationTone } from "./ConfirmActionDialog";

function action(actionType: ActionDescriptor["action_type"]): ActionDescriptor {
  return {
    descriptor_id: actionType,
    action_type: actionType,
    enabled: true,
    consequence_summary: "Apply the controlled action.",
  };
}

describe("confirmation action tone", () => {
  it("uses danger only for stopping or destructive actions", () => {
    expect(actionConfirmationTone(action("cancel_run"))).toBe("danger");
    expect(actionConfirmationTone(action("retire_method"))).toBe("danger");
    expect(actionConfirmationTone(action("reactivate_method"))).toBe("primary");
    expect(actionConfirmationTone(action("update_project_brief"))).toBe("primary");
  });
});
