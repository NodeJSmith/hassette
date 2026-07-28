import {
  designGroupClassName,
  designGroupLabelClassName,
  designHeadingClassName,
  designSectionClassName,
  designTokenCodeClassName,
} from "./design-showcase";

interface SpacingToken {
  name: string;
  cssVar: string;
  px: number;
}

const SPACING: SpacingToken[] = [
  { name: "px", cssVar: "--sp-px", px: 1 },
  { name: "0", cssVar: "--sp-0", px: 2 },
  { name: "1", cssVar: "--sp-1", px: 4 },
  { name: "1h", cssVar: "--sp-1h", px: 6 },
  { name: "2", cssVar: "--sp-2", px: 8 },
  { name: "3", cssVar: "--sp-3", px: 12 },
  { name: "3h", cssVar: "--sp-3h", px: 14 },
  { name: "4", cssVar: "--sp-4", px: 16 },
  { name: "5", cssVar: "--sp-5", px: 20 },
  { name: "6", cssVar: "--sp-6", px: 24 },
  { name: "7", cssVar: "--sp-7", px: 32 },
  { name: "8", cssVar: "--sp-8", px: 40 },
  { name: "9", cssVar: "--sp-9", px: 56 },
  { name: "10", cssVar: "--sp-10", px: 72 },
];

const MAX_SPACING_PX = SPACING[SPACING.length - 1].px;

const RADII = [
  { name: "sm", cssVar: "--r-sm", px: 6 },
  { name: "md", cssVar: "--r-md", px: 8 },
  { name: "lg", cssVar: "--r-lg", px: 12 },
  { name: "xl", cssVar: "--r-xl", px: 20 },
  { name: "pill", cssVar: "--r-pill", px: 999 },
];

const SHADOWS = [
  { name: "shadow-1", cssVar: "--shadow-1", label: "Subtle" },
  { name: "shadow-2", cssVar: "--shadow-2", label: "Medium" },
  { name: "shadow-3", cssVar: "--shadow-3", label: "Elevated" },
];

export function SpacingTokens() {
  return (
    <section className={designSectionClassName}>
      <h2 className={designHeadingClassName}>Spacing, Radii & Shadows</h2>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Spacing Scale</h3>
        <div className="flex flex-col gap-2">
          {SPACING.map((token) => (
            <div key={token.cssVar} className="grid grid-cols-[100px_40px_minmax(0,1fr)] items-center gap-3">
              <code className={designTokenCodeClassName}>{token.cssVar}</code>
              <span className="text-right font-mono text-xs text-foreground-secondary">{token.px}px</span>
              <div className="h-2 overflow-hidden rounded-sm bg-muted">
                <div
                  className="h-full min-w-px rounded-sm bg-primary"
                  style={{ width: `${(token.px / MAX_SPACING_PX) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Border Radius</h3>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(100px,1fr))] gap-4">
          {RADII.map((r) => (
            <div key={r.cssVar} className="flex flex-col items-center gap-1">
              <div
                className="size-14 border border-[var(--primary-border)] bg-[var(--primary-soft)]"
                style={{ borderRadius: `var(${r.cssVar})` }}
              />
              <span className="font-sans text-sm font-medium text-foreground">{r.name}</span>
              <code className={designTokenCodeClassName}>
                {r.cssVar} ({r.px}px)
              </code>
            </div>
          ))}
        </div>
      </div>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Elevation</h3>
        <div className="grid grid-cols-3 gap-7 rounded-lg bg-muted px-4 py-6">
          {SHADOWS.map((shadow) => (
            <div key={shadow.cssVar} className="flex flex-col items-center gap-3">
              <div className="aspect-[3/2] w-full rounded-md bg-card" style={{ boxShadow: `var(${shadow.cssVar})` }} />
              <span className="font-sans text-sm font-medium text-foreground">{shadow.label}</span>
              <code className={designTokenCodeClassName}>{shadow.cssVar}</code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
