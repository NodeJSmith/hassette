import styles from "./color-tokens.module.css";
import s from "./section.module.css";

interface SwatchGroup {
  label: string;
  tokens: { name: string; cssVar: string }[];
}

const GROUPS: SwatchGroup[] = [
  {
    label: "Surfaces",
    tokens: [
      { name: "page", cssVar: "--bg-page" },
      { name: "surface", cssVar: "--bg-surface" },
      { name: "sunken", cssVar: "--bg-sunken" },
      { name: "active", cssVar: "--bg-active" },
      { name: "chrome", cssVar: "--bg-chrome" },
    ],
  },
  {
    label: "Ink",
    tokens: [
      { name: "ink-1", cssVar: "--ink-1" },
      { name: "ink-2", cssVar: "--ink-2" },
      { name: "ink-3", cssVar: "--ink-3" },
      { name: "ink-4", cssVar: "--ink-4" },
    ],
  },
  {
    label: "Lines",
    tokens: [
      { name: "line-1", cssVar: "--line-1" },
      { name: "line-2", cssVar: "--line-2" },
      { name: "line-strong", cssVar: "--line-strong" },
    ],
  },
  {
    label: "Accent",
    tokens: [
      { name: "accent", cssVar: "--accent" },
      { name: "hover", cssVar: "--accent-hover" },
      { name: "ink", cssVar: "--accent-ink" },
      { name: "soft", cssVar: "--accent-soft" },
      { name: "border", cssVar: "--accent-border" },
      { name: "bg", cssVar: "--accent-bg" },
    ],
  },
  {
    label: "Status",
    tokens: [
      { name: "ok", cssVar: "--ok" },
      { name: "ok-bg", cssVar: "--ok-bg" },
      { name: "warn", cssVar: "--warn" },
      { name: "warn-bg", cssVar: "--warn-bg" },
      { name: "err", cssVar: "--err" },
      { name: "err-bg", cssVar: "--err-bg" },
      { name: "cancel", cssVar: "--cancel" },
      { name: "mute", cssVar: "--mute" },
      { name: "mute-bg", cssVar: "--mute-bg" },
    ],
  },
];

export function ColorTokens() {
  return (
    <section class={s.section}>
      <h2 class={s.heading}>Color Palette</h2>
      {GROUPS.map((group) => (
        <div key={group.label} class={s.group}>
          <h3 class={s.groupLabel}>{group.label}</h3>
          <div class={styles.grid}>
            {group.tokens.map((token) => (
              <div key={token.cssVar} class={styles.swatch}>
                <div class={styles.swatchColor} style={{ backgroundColor: `var(${token.cssVar})` }} />
                <span class={styles.swatchName}>{token.name}</span>
                <code class={s.tokenCode}>{token.cssVar}</code>
              </div>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
