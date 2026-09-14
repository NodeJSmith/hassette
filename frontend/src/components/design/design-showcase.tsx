import type { ReactNode } from "react";

export const designSectionClassName = "flex flex-col gap-6";

export const designHeadingClassName =
  "m-0 font-heading text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] tracking-[var(--text-h2-tracking)] text-foreground";

const designGroupClassName = "flex flex-col gap-3";

const designGroupLabelClassName =
  "m-0 font-sans text-sm font-semibold uppercase tracking-[var(--text-label-tracking)] text-muted-foreground";

export const designTokenCodeClassName = "font-mono text-xs text-muted-foreground";

interface ShowcaseGroupProps {
  label: string;
  children: ReactNode;
}

/** The labelled-group wrapper every design page section uses. Its class names are deliberately
 * unexported so this stays the only way to build one. */
export function ShowcaseGroup({ label, children }: ShowcaseGroupProps) {
  return (
    <div className={designGroupClassName}>
      <h3 className={designGroupLabelClassName}>{label}</h3>
      {children}
    </div>
  );
}
