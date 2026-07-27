import type { CSSProperties, ReactNode, Ref } from "react";
import { useRef } from "react";

interface TableCardProps {
  footer?: ReactNode;
  scrollHeight?: string;
  className?: string;
  "data-testid"?: string;
  children: ReactNode;
  containerRef?: Ref<HTMLDivElement>;
}

export function TableCard({
  footer,
  scrollHeight,
  className,
  "data-testid": testId,
  children,
  containerRef,
}: TableCardProps) {
  const fallbackRef = useRef<HTMLDivElement>(null);
  const ref = containerRef ?? fallbackRef;

  return (
    <div ref={ref} className={className} data-testid={testId}>
      <div
        className="ht-table-card-scroll"
        style={scrollHeight ? ({ "--table-scroll-height": scrollHeight } as CSSProperties) : undefined}
      >
        {children}
      </div>
      {footer && <div data-footer-slot>{footer}</div>}
    </div>
  );
}
