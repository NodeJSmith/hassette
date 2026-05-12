import { useRef } from "preact/hooks";
import { Card } from "./card";

interface TableCardProps {
  title?: preact.ComponentChildren;
  count?: preact.ComponentChildren;
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
        <div class="ht-table-toolbar">
          <div class="ht-table-toolbar__title">
            {title && <h2 class="ht-table-toolbar__heading">{title}</h2>}
            {count && <span class="ht-table-toolbar__note" aria-live="polite">{count}</span>}
          </div>
          {controls && <div class="ht-table-toolbar__controls">{controls}</div>}
        </div>
      )}
      <div class="ht-table-card-scroll" style={scrollHeight ? `--table-scroll-height: ${scrollHeight}` : undefined}>
        {children}
      </div>
    </Card>
  );
}
