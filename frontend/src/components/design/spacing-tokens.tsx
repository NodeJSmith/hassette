import s from "./section.module.css";
import styles from "./spacing-tokens.module.css";

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
    <section class={s.section}>
      <h2 class={s.heading}>Spacing, Radii & Shadows</h2>

      <div class={s.group}>
        <h3 class={s.groupLabel}>Spacing Scale</h3>
        <div class={styles.spacingList}>
          {SPACING.map((token) => (
            <div key={token.cssVar} class={styles.spacingRow}>
              <code class={s.tokenCode}>{token.cssVar}</code>
              <span class={styles.spacingValue}>{token.px}px</span>
              <div class={styles.spacingBarTrack}>
                <div class={styles.spacingBar} style={{ width: `${(token.px / MAX_SPACING_PX) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div class={s.group}>
        <h3 class={s.groupLabel}>Border Radius</h3>
        <div class={styles.radiiGrid}>
          {RADII.map((r) => (
            <div key={r.cssVar} class={styles.radiusItem}>
              <div class={styles.radiusBox} style={{ borderRadius: `var(${r.cssVar})` }} />
              <span class={styles.radiusLabel}>{r.name}</span>
              <code class={s.tokenCode}>
                {r.cssVar} ({r.px}px)
              </code>
            </div>
          ))}
        </div>
      </div>

      <div class={s.group}>
        <h3 class={s.groupLabel}>Elevation</h3>
        <div class={styles.shadowGrid}>
          {SHADOWS.map((shadow) => (
            <div key={shadow.cssVar} class={styles.shadowItem}>
              <div class={styles.shadowBox} style={{ boxShadow: `var(${shadow.cssVar})` }} />
              <span class={styles.shadowLabel}>{shadow.label}</span>
              <code class={s.tokenCode}>{shadow.cssVar}</code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
