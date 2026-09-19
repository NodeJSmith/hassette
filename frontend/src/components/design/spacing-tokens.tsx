import {
  designHeadingClassName,
  designSectionClassName,
  designTokenCodeClassName,
  ShowcaseGroup,
} from "./design-showcase";

interface SpacingToken {
  cssVar: string;
  px: number;
}

interface RadiusToken {
  name: string;
  cssVar: string;
  px: number;
}

interface ShadowToken {
  cssVar: string;
  label: string;
}

/**
 * Column widths for the spacing scale rows, applied as an inline grid template.
 * Tailwind resolves arbitrary values by scanning source text, so a `grid-cols-[...]`
 * class assembled from these constants would never emit CSS.
 */
const SPACING_VAR_COLUMN_WIDTH = "100px";
const SPACING_PX_COLUMN_WIDTH = "40px";
const SPACING_ROW_TEMPLATE = `${SPACING_VAR_COLUMN_WIDTH} ${SPACING_PX_COLUMN_WIDTH} minmax(0, 1fr)`;

const SPACING: SpacingToken[] = [
  { cssVar: "--sp-px", px: 1 },
  { cssVar: "--sp-0", px: 2 },
  { cssVar: "--sp-1", px: 4 },
  { cssVar: "--sp-1h", px: 6 },
  { cssVar: "--sp-2", px: 8 },
  { cssVar: "--sp-3", px: 12 },
  { cssVar: "--sp-3h", px: 14 },
  { cssVar: "--sp-4", px: 16 },
  { cssVar: "--sp-5", px: 20 },
  { cssVar: "--sp-6", px: 24 },
  { cssVar: "--sp-7", px: 32 },
  { cssVar: "--sp-8", px: 40 },
  { cssVar: "--sp-9", px: 56 },
  { cssVar: "--sp-10", px: 72 },
];

const MAX_SPACING_PX = SPACING[SPACING.length - 1].px;

const RADII: RadiusToken[] = [
  { name: "sm", cssVar: "--r-sm", px: 6 },
  { name: "md", cssVar: "--r-md", px: 8 },
  { name: "lg", cssVar: "--r-lg", px: 12 },
  { name: "xl", cssVar: "--r-xl", px: 20 },
  { name: "pill", cssVar: "--r-pill", px: 999 },
];

const SHADOWS: ShadowToken[] = [
  { cssVar: "--shadow-1", label: "Subtle" },
  { cssVar: "--shadow-2", label: "Medium" },
  { cssVar: "--shadow-3", label: "Elevated" },
];

export function SpacingTokens() {
  return (
    <section className={designSectionClassName}>
      <h2 className={designHeadingClassName}>Spacing, Radii & Shadows</h2>

      <ShowcaseGroup label="Spacing Scale">
        <div className="flex flex-col gap-2">
          {SPACING.map((token) => (
            <div
              key={token.cssVar}
              className="grid items-center gap-3"
              style={{ gridTemplateColumns: SPACING_ROW_TEMPLATE }}
            >
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
      </ShowcaseGroup>

      <ShowcaseGroup label="Border Radius">
        <div className="grid grid-cols-[repeat(auto-fill,minmax(100px,1fr))] gap-4">
          {RADII.map((radius) => (
            <div key={radius.cssVar} className="flex flex-col items-center gap-1">
              <div
                className="size-14 border border-[var(--primary-border)] bg-[var(--primary-soft)]"
                style={{ borderRadius: `var(${radius.cssVar})` }}
              />
              <span className="font-sans text-sm font-medium text-foreground">{radius.name}</span>
              <code className={designTokenCodeClassName}>
                {radius.cssVar} ({radius.px}px)
              </code>
            </div>
          ))}
        </div>
      </ShowcaseGroup>

      <ShowcaseGroup label="Elevation">
        <div className="grid grid-cols-3 gap-8 rounded-lg bg-muted px-4 py-6">
          {SHADOWS.map((shadow) => (
            <div key={shadow.cssVar} className="flex flex-col items-center gap-3">
              <div className="aspect-[3/2] w-full rounded-md bg-card" style={{ boxShadow: `var(${shadow.cssVar})` }} />
              <span className="font-sans text-sm font-medium text-foreground">{shadow.label}</span>
              <code className={designTokenCodeClassName}>{shadow.cssVar}</code>
            </div>
          ))}
        </div>
      </ShowcaseGroup>
    </section>
  );
}
