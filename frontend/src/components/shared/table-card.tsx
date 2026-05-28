import type { ComponentChildren } from "preact";
import { useRef } from "preact/hooks";

interface TableCardProps {
  footer?: ComponentChildren;
  scrollHeight?: string;
  class?: string;
  "data-testid"?: string;
  children: ComponentChildren;
  containerRef?: preact.Ref<HTMLDivElement>;
}

export function TableCard({
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
    <div ref={ref} class={className} data-testid={testId}>
      <div class="ht-table-card-scroll" style={scrollHeight ? `--table-scroll-height: ${scrollHeight}` : undefined}>
        {children}
      </div>
      {footer && <div data-footer-slot>{footer}</div>}
    </div>
  );
}
