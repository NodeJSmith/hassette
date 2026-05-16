import { useRef } from "preact/hooks";
import { Card } from "./card";

interface TableCardProps {
  /** @deprecated Toolbar is being removed — migrate controls to inline page layout. */
  title?: preact.ComponentChildren;
  /** @deprecated Toolbar is being removed — use TableFooter count prop instead. */
  count?: preact.ComponentChildren;
  /** @deprecated Toolbar is being removed — migrate controls to inline page layout. */
  controls?: preact.ComponentChildren;
  scrollHeight?: string;
  class?: string;
  children: preact.ComponentChildren;
  containerRef?: preact.Ref<HTMLDivElement>;
}

export function TableCard({ title, count, controls, scrollHeight, class: className, children, containerRef }: TableCardProps) {
  const fallbackRef = useRef<HTMLDivElement>(null);
  const ref = containerRef ?? fallbackRef;

  return (
    <Card variant="compact" class={className} containerRef={ref}>
      {(title || count || controls) && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "var(--sp-3)", marginBottom: "var(--sp-3)", flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "var(--sp-3)" }}>
            {title && <h2 style={{ fontFamily: "var(--font-display)", fontSize: "var(--fs-h3)", fontWeight: 400, margin: 0 }}>{title}</h2>}
            {count && <span style={{ fontSize: "var(--fs-micro)", color: "var(--ink-3)" }} aria-live="polite">{count}</span>}
          </div>
          {controls && <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-2)", flexWrap: "wrap" }}>{controls}</div>}
        </div>
      )}
      <div class="ht-table-card-scroll" style={scrollHeight ? `--table-scroll-height: ${scrollHeight}` : undefined}>
        {children}
      </div>
    </Card>
  );
}
