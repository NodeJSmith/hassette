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
        className="overflow-auto rounded-md border border-[var(--border-strong)] max-h-[var(--table-scroll-height)]"
        data-testid="table-card-scroll"
        style={{ "--table-scroll-height": scrollHeight ?? "calc(100vh - 310px)" } as CSSProperties}
      >
        {children}
      </div>
      {footer && <div data-footer-slot>{footer}</div>}
    </div>
  );
}
