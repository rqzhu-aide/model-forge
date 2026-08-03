import { useEffect, useId, useRef, useState } from "react";
import type { ActionDescriptor } from "../api/types";

export function actionConfirmationTone(action: ActionDescriptor): "danger" | "primary" {
  return action.action_type === "cancel_run" || action.action_type === "retire_method"
    ? "danger"
    : "primary";
}

export function ConfirmActionDialog({
  action,
  open,
  title,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: {
  action: ActionDescriptor;
  open: boolean;
  title: string;
  confirmLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [reason, setReason] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open) setReason("");
  }, [open]);

  const confirmationTone = actionConfirmationTone(action);
  return (
    <dialog
      ref={dialogRef}
      className="dialog"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
      onClose={() => {
        if (open && !busy) onCancel();
      }}
    >
      <form
        method="dialog"
        onSubmit={(event) => {
          event.preventDefault();
          if (!busy && (!action.requires_reason || reason.trim())) onConfirm(reason.trim());
        }}
      >
        <p className="eyebrow">User-controlled action</p>
        <h2 id={titleId}>{title}</h2>
        <p id={descriptionId}>{action.consequence_summary}</p>
        {action.requires_reason ? (
          <label className="field">
            <span>Reason</span>
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              required
              maxLength={4000}
              autoFocus
            />
            <small>This explanation becomes part of the typed command.</small>
          </label>
        ) : null}
        <div className="dialog__actions">
          <button type="button" className="button button--quiet" onClick={onCancel} disabled={busy}>
            Back
          </button>
          <button
            type="submit"
            className={`button button--${confirmationTone}`}
            disabled={busy || (action.requires_reason === true && !reason.trim())}
          >
            {busy ? "Submitting..." : confirmLabel}
          </button>
        </div>
      </form>
    </dialog>
  );
}
