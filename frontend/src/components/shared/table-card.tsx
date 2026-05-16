import { useRef } from "preact/hooks";
import type { ComponentChildren } from "preact";
import { Card } from "./card";

interface TableCardProps {
  search?: ComponentChildren;
  footer?: ComponentChildren;
  scrollHeight?: string;
  class?: string;
  "data-testid"?: string;
  children: ComponentChildren;
  containerRef?: preact.Ref<HTMLDivElement>;
}

export function TableCard({
  search,
  footer,
  scrollHeight,
  class: className,
  "data-testid": testId,
  children,
  containerRef,
}: TableCardProps) {
  const fallbackRef = useRef<HTMLDivElement>(null);
  const ref = containerRef ?? fallbackRef;

  return (
    <Card variant="compact" class={className} containerRef={ref} data-testid={testId}>
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
