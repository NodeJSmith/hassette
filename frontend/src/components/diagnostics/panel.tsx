import type { ReactNode } from "react";

// Panels apply cardVariants() directly to the <section> instead of rendering <Card> (a <div>).
// Each panel is a page landmark that screen-reader users navigate via aria-label — wrapping it
// in Card's <div> would lose that semantic, so the styling is applied without the element.
import { cardVariants } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// Deliberately not `AlertShell tone="warning"`: that shell owns its own geometry (mb-4,
// rounded-md) for standalone page-level banners, while these sit inside a panel whose
// flex column already supplies the spacing. Same tokens, different container.
/** Warning banner shown inside a panel — shared by the telemetry and logging panels. */
export const PANEL_WARNING_CLASS =
  "rounded-sm border border-[var(--status-warning)] bg-[var(--status-warning-bg)] px-4 py-3 text-sm text-[var(--status-warning)]";

const PANEL_HEADING_CLASS =
  "m-0 font-sans text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] text-foreground";

interface PanelProps {
  /** Heading text, rendered lowercase as authored. */
  title: string;
  /** Accessible name for the landmark — spelled out for screen readers, so not always `title`. */
  ariaLabel: string;
  /**
   * Rendered on the heading's baseline, e.g. the services panel's "stale" chip. Pass `null`
   * rather than omitting the prop for an aside that comes and goes — the heading keeps its row
   * layout instead of restructuring each time the aside appears or disappears.
   */
  headingAside?: ReactNode;
  "data-testid"?: string;
  children: ReactNode;
}

/** Card-styled landmark section with a heading — the shell every diagnostics panel shares. */
export function Panel({ title, ariaLabel, headingAside, "data-testid": testId, children }: PanelProps) {
  const heading = <h2 className={PANEL_HEADING_CLASS}>{title}</h2>;

  return (
    <section
      className={cn(cardVariants({ variant: "default" }), "flex flex-col gap-3")}
      aria-label={ariaLabel}
      data-testid={testId}
    >
      {headingAside === undefined ? (
        heading
      ) : (
        <div className="flex items-baseline gap-3">
          {heading}
          {headingAside}
        </div>
      )}
      {children}
    </section>
  );
}
