import type { ReactNode } from "react";

import { cardVariants } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** Flattens `AlertShell`'s standalone margin and radius — a panel's flex column already supplies the gap. */
export const PANEL_BANNER_CLASS = "mb-0 rounded-sm text-sm text-[var(--status-warning)]";

const PANEL_HEADING_CLASS =
  "m-0 font-sans text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] text-foreground";

interface PanelProps {
  /** Heading text, rendered lowercase as authored. */
  title: string;
  /** Accessible name for the landmark — spelled out for screen readers, so not always `title`. */
  ariaLabel: string;
  /** Rendered on the heading's baseline, e.g. the services panel's "stale" chip. */
  headingAside?: ReactNode;
  "data-testid"?: string;
  children: ReactNode;
}

/** Card-styled landmark section with a heading — the shell every diagnostics panel shares. */
export function Panel({ title, ariaLabel, headingAside, "data-testid": testId, children }: PanelProps) {
  return (
    // cardVariants() is applied to the <section> rather than rendering <Card> (a <div>) so the
    // panel keeps its landmark semantics for screen-reader users navigating by aria-label.
    <section
      className={cn(cardVariants({ variant: "default" }), "flex flex-col gap-3")}
      aria-label={ariaLabel}
      data-testid={testId}
    >
      <div className="flex items-baseline gap-3">
        <h2 className={PANEL_HEADING_CLASS}>{title}</h2>
        {headingAside}
      </div>
      {children}
    </section>
  );
}
