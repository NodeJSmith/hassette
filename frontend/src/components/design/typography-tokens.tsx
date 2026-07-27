import s from "./section.module.css";
import styles from "./typography-tokens.module.css";

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
    <section className={s.section}>
      <h2 className={s.heading}>Typography</h2>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Font Stacks</h3>
        <div className={styles.stackList}>
          {FONT_STACKS.map((stack) => (
            <div key={stack.cssVar} className={styles.stackRow}>
              <code className={s.tokenCode}>{stack.cssVar}</code>
              <span className={styles.stackSample} style={{ fontFamily: `var(${stack.cssVar})` }}>
                {stack.sample}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Type Scale</h3>
        <div className={styles.scaleList}>
          {TYPE_SCALE.map((spec) => (
            <div key={spec.sizeVar} className={styles.scaleRow}>
              <div className={styles.scaleMeta}>
                <span className={styles.scaleLabel}>{spec.label}</span>
                <code className={s.tokenCode}>{spec.sizeVar}</code>
              </div>
              <span
                className={styles.scaleSample}
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

      <div className={s.group}>
        <h3 className={s.groupLabel}>Weights</h3>
        <div className={styles.weightList}>
          {WEIGHTS.map((w) => (
            <div key={w.cssVar} className={styles.weightRow}>
              <code className={s.tokenCode}>{w.cssVar}</code>
              <span className={styles.weightSample} style={{ fontWeight: `var(${w.cssVar})` }}>
                {w.label} ({w.value})
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
