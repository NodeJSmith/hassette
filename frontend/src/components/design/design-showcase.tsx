import type { ReactNode } from "react";

export const DESIGN_SECTION_CLASS = "flex flex-col gap-6";

export const DESIGN_HEADING_CLASS =
  "m-0 font-[family-name:var(--font-heading)] text-[length:var(--text-h2)] font-semibold leading-[var(--text-h2-leading)] tracking-[var(--text-h2-tracking)] text-foreground";

const DESIGN_GROUP_CLASS = "flex flex-col gap-3";

const DESIGN_GROUP_LABEL_CLASS =
  "m-0 font-sans text-sm font-semibold uppercase tracking-[var(--text-label-tracking)] text-muted-foreground";

export const DESIGN_TOKEN_CODE_CLASS = "font-mono text-xs text-muted-foreground";

interface ShowcaseGroupProps {
  label: string;
  children: ReactNode;
}

/** The labelled-group wrapper every design page section uses. Its class names are deliberately
 * unexported so this stays the only way to build one. */
export function ShowcaseGroup({ label, children }: ShowcaseGroupProps) {
  return (
    <div className={DESIGN_GROUP_CLASS}>
      <h3 className={DESIGN_GROUP_LABEL_CLASS}>{label}</h3>
      {children}
    </div>
  );
}
