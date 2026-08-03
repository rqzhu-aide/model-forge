import type { ReactNode } from "react";
import { ApiError } from "../api/client";

export function LoadingState({ label = "Loading research state…" }: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span className="loading-state__spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({
  error,
  title = "This view is unavailable",
  action,
}: {
  error: unknown;
  title?: string;
  action?: ReactNode;
}) {
  const apiError = error instanceof ApiError ? error : undefined;
  const message = error instanceof Error ? error.message : "An unexpected error occurred.";
  return (
    <div className="message message--error" role="alert">
      <div>
        <strong>{title}</strong>
        <p>{message}</p>
        {apiError?.smallestCorrection && (
          <p>
            <span className="message__label">Next step:</span> {apiError.smallestCorrection}
          </p>
        )}
        {apiError?.code && <code className="message__code">{apiError.code}</code>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state__mark" aria-hidden="true">○</span>
      <div>
        <strong>{title}</strong>
        <div className="empty-state__copy">{children}</div>
      </div>
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
}
