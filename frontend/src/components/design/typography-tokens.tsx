import {
  designGroupClassName,
  designGroupLabelClassName,
  designHeadingClassName,
  designSectionClassName,
  designTokenCodeClassName,
} from "./design-showcase";

interface TypeSpec {
  label: string;
  sizeVar: string;
  lineHeightVar: string;
  trackingVar?: string;
  sample: string;
}

const TYPE_SCALE: TypeSpec[] = [
  {
    label: "Display",
    sizeVar: "--fs-display",
    lineHeightVar: "--lh-display",
    trackingVar: "--tr-display",
    sample: "Hassette",
  },
  { label: "H1", sizeVar: "--fs-h1", lineHeightVar: "--lh-h1", trackingVar: "--tr-h1", sample: "Page heading" },
  { label: "H2", sizeVar: "--fs-h2", lineHeightVar: "--lh-h2", trackingVar: "--tr-h2", sample: "Section heading" },
  { label: "H3", sizeVar: "--fs-h3", lineHeightVar: "--lh-h3", trackingVar: "--tr-h3", sample: "Card heading" },
  {
    label: "Body",
    sizeVar: "--fs-body",
    lineHeightVar: "--lh-body",
    sample: "Default paragraph text for descriptions and content.",
  },
  { label: "Small", sizeVar: "--fs-small", lineHeightVar: "--lh-small", sample: "Secondary labels and metadata" },
  { label: "Micro", sizeVar: "--fs-micro", lineHeightVar: "--lh-micro", sample: "Timestamps, footnotes" },
  { label: "XS", sizeVar: "--fs-xs", lineHeightVar: "--lh-xs", sample: "BADGE LABELS" },
];

const FONT_STACKS = [
  { label: "Display", cssVar: "--font-display", sample: "Newsreader — The quick brown fox" },
  { label: "Body", cssVar: "--font-body", sample: "Geist — The quick brown fox jumps over the lazy dog" },
  { label: "Mono", cssVar: "--font-mono", sample: "Geist Mono — 0123456789 => {}" },
];

const WEIGHTS = [
  { label: "Normal", cssVar: "--fw-normal", value: "400" },
  { label: "Medium", cssVar: "--fw-medium", value: "500" },
  { label: "Semibold", cssVar: "--fw-semibold", value: "600" },
  { label: "Bold", cssVar: "--fw-bold", value: "700" },
];

export function TypographyTokens() {
  return (
    <section className={designSectionClassName}>
      <h2 className={designHeadingClassName}>Typography</h2>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Font Stacks</h3>
        <div className="flex flex-col gap-4">
          {FONT_STACKS.map((stack) => (
            <div key={stack.cssVar} className="flex flex-col gap-1">
              <code className={designTokenCodeClassName}>{stack.cssVar}</code>
              <span
                className="text-[length:var(--text-h2)] text-foreground"
                style={{ fontFamily: `var(${stack.cssVar})` }}
              >
                {stack.sample}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Type Scale</h3>
        <div className="flex flex-col gap-5">
          {TYPE_SCALE.map((spec) => (
            <div
              key={spec.sizeVar}
              className="flex flex-col gap-1 border-b border-[var(--border-subtle)] pb-5 last:border-b-0 last:pb-0"
            >
              <div className="flex items-baseline gap-3">
                <span className="font-sans text-sm font-semibold text-foreground-secondary">{spec.label}</span>
                <code className={designTokenCodeClassName}>{spec.sizeVar}</code>
              </div>
              <span
                className="font-sans text-foreground"
                style={{
                  fontSize: `var(${spec.sizeVar})`,
                  lineHeight: `var(${spec.lineHeightVar})`,
                  letterSpacing: spec.trackingVar ? `var(${spec.trackingVar})` : undefined,
                }}
              >
                {spec.sample}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className={designGroupClassName}>
        <h3 className={designGroupLabelClassName}>Weights</h3>
        <div className="flex flex-col gap-3">
          {WEIGHTS.map((w) => (
            <div key={w.cssVar} className="flex items-baseline gap-4">
              <code className={designTokenCodeClassName}>{w.cssVar}</code>
              <span
                className="font-sans text-[length:var(--text-h3)] text-foreground"
                style={{ fontWeight: `var(${w.cssVar})` }}
              >
                {w.label} ({w.value})
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
