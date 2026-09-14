import type * as React from "react";

export const designSectionClassName = "flex flex-col gap-6";

export const designHeadingClassName =
  "m-0 font-heading text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] tracking-[var(--text-h2-tracking)] text-foreground";

export const designGroupClassName = "flex flex-col gap-3";

export const designGroupLabelClassName =
  "m-0 font-sans text-sm font-semibold uppercase tracking-[var(--text-label-tracking)] text-muted-foreground";

export const designTokenCodeClassName = "font-mono text-xs text-muted-foreground";

interface ShowcaseGroupProps {
  label: string;
  children: React.ReactNode;
}

/** A labelled group of showcase examples — the repeated wrapper shape used across the design page. */
export function ShowcaseGroup({ label, children }: ShowcaseGroupProps) {
  return (
    <div className={designGroupClassName}>
      <h3 className={designGroupLabelClassName}>{label}</h3>
      {children}
    </div>
  );
}
