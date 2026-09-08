import type { ReactNode } from "react";

// Panels apply cardVariants() directly to the <section> instead of rendering <Card> (a <div>).
// Each panel is a page landmark that screen-reader users navigate via aria-label — wrapping it
// in Card's <div> would lose that semantic, so the styling is applied without the element.
import { cardVariants } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/**
 * Content classes for an `AlertShell tone="warning"` nested in a panel. `cn()` runs twMerge, so
 * `mb-0 rounded-sm` overrides the shell's standalone `mb-4 rounded-md` — the panel's flex column
 * already supplies the gap. The text color and size live here because `AlertShell` applies no text
 * styles of its own; its warning tone sets border and background only.
 */
export const PANEL_BANNER_CLASS = "mb-0 rounded-sm text-sm text-[var(--status-warning)]";

const PANEL_HEADING_CLASS =
  "m-0 font-sans text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] text-foreground";

interface PanelProps {
  /** Heading text, rendered lowercase as authored. */
  title: string;
  /** Accessible name for the landmark — spelled out for screen readers, so not always `title`. */
  ariaLabel: string;
  /**
   * Rendered on the heading's baseline, e.g. the services panel's "stale" chip. The heading row
   * is always laid out the same way, so an aside that comes and goes does not restructure it —
   * omitting the prop, `null`, and `undefined` are interchangeable.
   */
  headingAside?: ReactNode;
  "data-testid"?: string;
  children: ReactNode;
}

/** Card-styled landmark section with a heading — the shell every diagnostics panel shares. */
export function Panel({ title, ariaLabel, headingAside, "data-testid": testId, children }: PanelProps) {
  return (
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
