import { useRef } from "preact/hooks";
import type { ComponentChildren } from "preact";
import { Card } from "./card";

interface TableCardProps {
  /** Search input element — renders above the scroll area with a border-bottom separator. */
  search?: ComponentChildren;
  /** Footer element (e.g., TableFooter) — renders below the scroll area. */
  footer?: ComponentChildren;
  scrollHeight?: string;
  class?: string;
  children: ComponentChildren;
  containerRef?: preact.Ref<HTMLDivElement>;

  // ─── Deprecated toolbar props ──────────────────────────────────────────
  // These remain for backward compat while T04/T05/T06 migrate page callers.
  // Remove once apps.tsx and handlers.tsx are migrated.
  /** @deprecated Toolbar is being removed — migrate controls to inline page layout. */
  title?: ComponentChildren;
  /** @deprecated Toolbar is being removed — use TableFooter count prop instead. */
  count?: ComponentChildren;
  /** @deprecated Toolbar is being removed — migrate controls to inline page layout. */
  controls?: ComponentChildren;
}

export function TableCard({
  search,
  footer,
  scrollHeight,
  class: className,
  children,
  containerRef,
  // deprecated
  title,
  count,
  controls,
}: TableCardProps) {
  const fallbackRef = useRef<HTMLDivElement>(null);
  const ref = containerRef ?? fallbackRef;

  const showDeprecatedToolbar = !search && (title || count || controls);

  return (
    <Card variant="compact" class={className} containerRef={ref}>
      {showDeprecatedToolbar && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--sp-3)", marginBottom: "var(--sp-3)", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "var(--sp-3)" }}>
            {title && <h2 style={{ fontFamily: "var(--font-display)", fontSize: "var(--fs-h3)", fontWeight: 400, margin: 0 }}>{title}</h2>}
            {count && <span style={{ fontSize: "var(--fs-micro)", color: "var(--ink-3)" }} aria-live="polite">{count}</span>}
          </div>
          {controls && <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap" }}>{controls}</div>}
        </div>
      )}
      {search && (
        <div
          data-search-bar
          style={{
            padding: "var(--sp-2) var(--sp-3)",
            borderBottom: "1px solid var(--line-2)",
          }}
        >
          {search}
        </div>
      )}
      <div class="ht-table-card-scroll" style={scrollHeight ? `--table-scroll-height: ${scrollHeight}` : undefined}>
        {children}
      </div>
      {footer && (
        <div data-footer-slot>
          {footer}
        </div>
      )}
    </Card>
  );
}
