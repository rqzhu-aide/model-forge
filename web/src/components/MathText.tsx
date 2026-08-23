import { useMemo } from "react";
import katex from "katex";

/**
 * Render text that may contain LaTeX math segments.
 *
 * Supported delimiters: $...$ (inline) and $$...$$ (display). Segments that
 * fail to parse are shown as their raw source (never crash the view).
 * KaTeX output is generated locally from trusted project data.
 */
export function MathText({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => renderMathText(text), [text]);
  return (
    <span
      className={className}
      // eslint-disable-next-line react/no-danger -- KaTeX output, locally generated
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMathText(text: string): string {
  // Split on $$...$$ first (display math), then $...$ (inline).
  const segments = text.split(/(\$\$[^$]+\$\$|\$[^$]+\$)/g);
  return segments
    .map((segment) => {
      if (segment.startsWith("$$") && segment.endsWith("$$") && segment.length > 4) {
        return renderKatex(segment.slice(2, -2), true);
      }
      if (segment.startsWith("$") && segment.endsWith("$") && segment.length > 2) {
        return renderKatex(segment.slice(1, -1), false);
      }
      return escapeHtml(segment);
    })
    .join("");
}

function renderKatex(source: string, displayMode: boolean): string {
  try {
    return katex.renderToString(source, {
      displayMode,
      throwOnError: true,
      strict: "warn",
    });
  } catch {
    // Fall back to the raw source so malformed math stays visible.
    return escapeHtml(`$${displayMode ? "$" : ""}${source}${displayMode ? "$" : ""}$`);
  }
}
