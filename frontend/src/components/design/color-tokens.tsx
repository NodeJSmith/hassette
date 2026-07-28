import {
  designGroupClassName,
  designGroupLabelClassName,
  designHeadingClassName,
  designSectionClassName,
  designTokenCodeClassName,
} from "./design-showcase";

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
    <section className={designSectionClassName}>
      <h2 className={designHeadingClassName}>Color Palette</h2>
      {GROUPS.map((group) => (
        <div key={group.label} className={designGroupClassName}>
          <h3 className={designGroupLabelClassName}>{group.label}</h3>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(140px,1fr))] gap-3">
            {group.tokens.map((token) => (
              <div key={token.cssVar} className="flex flex-col gap-1">
                <div
                  className="h-14 rounded-md border border-border"
                  style={{ backgroundColor: `var(${token.cssVar})` }}
                />
                <span className="font-sans text-sm font-medium text-foreground">{token.name}</span>
                <code className={designTokenCodeClassName}>{token.cssVar}</code>
              </div>
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
