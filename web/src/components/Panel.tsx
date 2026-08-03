import type { ReactNode } from "react";

interface PanelProps {
  title?: string;
  eyebrow?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}

export function Panel({
  title,
  eyebrow,
  description,
  actions,
  children,
  className = "",
  id,
}: PanelProps) {
  const titleId = id && title ? `${id}-title` : undefined;
  return (
    <section
      className={`panel ${className}`.trim()}
      id={id}
      aria-labelledby={titleId}
    >
      {(title || eyebrow || description || actions) && (
        <header className="panel__header">
          <div>
            {eyebrow && <p className="eyebrow">{eyebrow}</p>}
            {title && <h2 id={titleId}>{title}</h2>}
            {description && <p className="panel__description">{description}</p>}
          </div>
          {actions && <div className="panel__actions">{actions}</div>}
        </header>
      )}
      <div className="panel__body">{children}</div>
    </section>
  );
}
