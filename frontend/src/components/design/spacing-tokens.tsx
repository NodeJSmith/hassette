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
    <section className={s.section}>
      <h2 className={s.heading}>Spacing, Radii & Shadows</h2>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Spacing Scale</h3>
        <div className={styles.spacingList}>
          {SPACING.map((token) => (
            <div key={token.cssVar} className={styles.spacingRow}>
              <code className={s.tokenCode}>{token.cssVar}</code>
              <span className={styles.spacingValue}>{token.px}px</span>
              <div className={styles.spacingBarTrack}>
                <div className={styles.spacingBar} style={{ width: `${(token.px / MAX_SPACING_PX) * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Border Radius</h3>
        <div className={styles.radiiGrid}>
          {RADII.map((r) => (
            <div key={r.cssVar} className={styles.radiusItem}>
              <div className={styles.radiusBox} style={{ borderRadius: `var(${r.cssVar})` }} />
              <span className={styles.radiusLabel}>{r.name}</span>
              <code className={s.tokenCode}>
                {r.cssVar} ({r.px}px)
              </code>
            </div>
          ))}
        </div>
      </div>

      <div className={s.group}>
        <h3 className={s.groupLabel}>Elevation</h3>
        <div className={styles.shadowGrid}>
          {SHADOWS.map((shadow) => (
            <div key={shadow.cssVar} className={styles.shadowItem}>
              <div className={styles.shadowBox} style={{ boxShadow: `var(${shadow.cssVar})` }} />
              <span className={styles.shadowLabel}>{shadow.label}</span>
              <code className={s.tokenCode}>{shadow.cssVar}</code>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
