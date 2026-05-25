import { useCallback, useEffect, useRef, useState } from "preact/hooks";

import styles from "./design-tuner.module.css";

const SPACING_TOKENS = [
  "--sp-0",
  "--sp-1",
  "--sp-2",
  "--sp-3",
  "--sp-4",
  "--sp-5",
  "--sp-6",
  "--sp-7",
  "--sp-8",
  "--sp-9",
  "--sp-10",
  "--sp-1h",
  "--sp-3h",
];

const RADIUS_TOKENS = ["--r-sm", "--r-md", "--r-lg", "--r-xl"];

// Sync with --shadow-* definitions in tokens.css
const SHADOW_BASES = {
  light: {
    "--shadow-1": { y: 1, blur: 2, alpha: 0.04 },
    "--shadow-2": {
      layers: [
        { y: 2, blur: 8, alpha: 0.06 },
        { y: 1, blur: 2, alpha: 0.04 },
      ],
    },
    "--shadow-3": {
      layers: [
        { y: 8, blur: 24, alpha: 0.08 },
        { y: 2, blur: 6, alpha: 0.04 },
      ],
    },
  },
  dark: {
    "--shadow-1": { y: 1, blur: 2, alpha: 0.3 },
    "--shadow-2": {
      layers: [
        { y: 2, blur: 8, alpha: 0.4 },
        { y: 1, blur: 2, alpha: 0.3 },
      ],
    },
    "--shadow-3": {
      layers: [
        { y: 8, blur: 24, alpha: 0.5 },
        { y: 2, blur: 6, alpha: 0.3 },
      ],
    },
  },
};

interface SliderConfig {
  label: string;
  min: number;
  max: number;
  step: number;
  initial: number;
  format: (v: number) => string;
}

const SLIDERS: Record<string, SliderConfig> = {
  hue: { label: "Hue", min: 0, max: 360, step: 1, initial: 255, format: (v) => `${v}` },
  chroma: { label: "Chroma", min: 0.02, max: 0.25, step: 0.005, initial: 0.09, format: (v) => v.toFixed(3) },
  density: { label: "Density", min: 0.6, max: 1.6, step: 0.05, initial: 1, format: (v) => `${v.toFixed(2)}x` },
  surfaceGap: {
    label: "Surface gap",
    min: 0,
    max: 0.06,
    step: 0.002,
    initial: 0.01,
    format: (v) => v.toFixed(3),
  },
  shadowIntensity: { label: "Shadows", min: 0, max: 3, step: 0.1, initial: 1, format: (v) => `${v.toFixed(1)}x` },
  fontSize: {
    label: "Font offset",
    min: -2,
    max: 4,
    step: 0.5,
    initial: 0,
    format: (v) => `${v > 0 ? "+" : ""}${v}px`,
  },
  radiusScale: { label: "Radius", min: 0, max: 3, step: 0.1, initial: 1, format: (v) => `${v.toFixed(1)}x` },
};

function readBaselines(): Record<string, number> {
  const root = getComputedStyle(document.documentElement);
  const baselines: Record<string, number> = {};
  for (const token of SPACING_TOKENS) {
    baselines[token] = parseFloat(root.getPropertyValue(token));
  }
  for (const token of RADIUS_TOKENS) {
    baselines[token] = parseFloat(root.getPropertyValue(token));
  }
  baselines["--fs-display"] = parseFloat(root.getPropertyValue("--fs-display"));
  baselines["--fs-h1"] = parseFloat(root.getPropertyValue("--fs-h1"));
  baselines["--fs-h2"] = parseFloat(root.getPropertyValue("--fs-h2"));
  baselines["--fs-h3"] = parseFloat(root.getPropertyValue("--fs-h3"));
  baselines["--fs-body"] = parseFloat(root.getPropertyValue("--fs-body"));
  baselines["--fs-small"] = parseFloat(root.getPropertyValue("--fs-small"));
  baselines["--fs-micro"] = parseFloat(root.getPropertyValue("--fs-micro"));
  baselines["--fs-xs"] = parseFloat(root.getPropertyValue("--fs-xs"));
  baselines["--fs-stat"] = parseFloat(root.getPropertyValue("--fs-stat"));
  baselines["--fs-badge"] = parseFloat(root.getPropertyValue("--fs-badge"));
  baselines["--fs-mono-sm"] = parseFloat(root.getPropertyValue("--fs-mono-sm"));
  baselines["--fs-mono-md"] = parseFloat(root.getPropertyValue("--fs-mono-md"));
  return baselines;
}

function isDark(): boolean {
  return document.documentElement.getAttribute("data-theme") === "dark";
}

function buildShadow(base: { y: number; blur: number; alpha: number }, intensity: number, dark: boolean): string {
  const color = dark ? "0, 0, 0" : "20, 22, 26";
  return `0 ${base.y}px ${base.blur}px rgba(${color}, ${(base.alpha * intensity).toFixed(3)})`;
}

function applyShadows(intensity: number) {
  const root = document.documentElement;
  const theme = isDark() ? "dark" : "light";
  const bases = SHADOW_BASES[theme];

  for (const [token, def] of Object.entries(bases)) {
    if ("layers" in def) {
      root.style.setProperty(token, def.layers.map((l) => buildShadow(l, intensity, isDark())).join(", "));
    } else {
      root.style.setProperty(token, buildShadow(def, intensity, isDark()));
    }
  }
}

export function DesignTuner() {
  const [open, setOpen] = useState(true);
  const [values, setValues] = useState(() =>
    Object.fromEntries(Object.entries(SLIDERS).map(([k, s]) => [k, s.initial])),
  );
  const baselinesRef = useRef<Record<string, number> | null>(null);

  useEffect(() => {
    baselinesRef.current = readBaselines();
  }, []);

  const apply = useCallback((key: string, val: number) => {
    const root = document.documentElement;
    const baselines = baselinesRef.current;
    if (!baselines) return;

    switch (key) {
      case "hue":
        root.style.setProperty("--accent-hue", `${val}`);
        break;
      case "chroma":
        root.style.setProperty("--accent-chroma", `${val}`);
        break;
      case "density":
        for (const token of SPACING_TOKENS) {
          root.style.setProperty(token, `${(baselines[token] * val).toFixed(1)}px`);
        }
        break;
      case "surfaceGap": {
        const pageLightness = isDark() ? 0.13 : 0.97;
        root.style.setProperty("--bg-page", `oklch(${pageLightness} 0.003 80)`);
        root.style.setProperty("--bg-surface", `oklch(${(pageLightness + val).toFixed(4)} 0.003 80)`);
        break;
      }
      case "shadowIntensity":
        applyShadows(val);
        break;
      case "fontSize":
        for (const token of Object.keys(baselines).filter((k) => k.startsWith("--fs-"))) {
          root.style.setProperty(token, `${(baselines[token] + val).toFixed(1)}px`);
        }
        break;
      case "radiusScale":
        for (const token of RADIUS_TOKENS) {
          root.style.setProperty(token, `${(baselines[token] * val).toFixed(1)}px`);
        }
        break;
    }
  }, []);

  const handleChange = useCallback(
    (key: string, val: number) => {
      setValues((prev) => ({ ...prev, [key]: val }));
      apply(key, val);
    },
    [apply],
  );

  const handleReset = useCallback(() => {
    const root = document.documentElement;
    setValues(Object.fromEntries(Object.entries(SLIDERS).map(([k, s]) => [k, s.initial])));
    const allOverrides = [
      ...SPACING_TOKENS,
      ...RADIUS_TOKENS,
      ...Object.keys(baselinesRef.current ?? {}).filter((k) => k.startsWith("--fs-")),
      "--shadow-1",
      "--shadow-2",
      "--shadow-3",
      "--bg-page",
      "--bg-surface",
      "--accent-hue",
      "--accent-chroma",
    ];
    for (const token of allOverrides) {
      root.style.removeProperty(token);
    }
    baselinesRef.current = readBaselines();
  }, []);

  if (!open) {
    return (
      <button type="button" class={styles.toggle} onClick={() => setOpen(true)} title="Design Tuner">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 1v6m0 6v6m-5.2-14.8l4.2 4.2m0 0l4.2-4.2M6.8 18.2l4.2-4.2m0 0l4.2 4.2M1 12h6m6 0h6" />
        </svg>
      </button>
    );
  }

  return (
    <div class={styles.panel}>
      <div class={styles.header}>
        <span>Design Tuner</span>
        <button type="button" class={styles.closeBtn} onClick={() => setOpen(false)}>
          &times;
        </button>
      </div>
      <div class={styles.body}>
        {/* Accent color */}
        <div class={styles.group}>
          <div class={styles.label}>
            <span>Hue</span>
            <span class={styles.value}>{SLIDERS.hue.format(values.hue)}</span>
          </div>
          <input
            type="range"
            class={styles.hueSlider}
            min={SLIDERS.hue.min}
            max={SLIDERS.hue.max}
            step={SLIDERS.hue.step}
            value={values.hue}
            onInput={(e) => handleChange("hue", parseFloat((e.target as HTMLInputElement).value))}
          />
        </div>
        <div class={styles.group}>
          <div class={styles.label}>
            <span>Chroma</span>
            <span class={styles.value}>{SLIDERS.chroma.format(values.chroma)}</span>
          </div>
          <input
            type="range"
            class={styles.slider}
            min={SLIDERS.chroma.min}
            max={SLIDERS.chroma.max}
            step={SLIDERS.chroma.step}
            value={values.chroma}
            onInput={(e) => handleChange("chroma", parseFloat((e.target as HTMLInputElement).value))}
          />
        </div>

        <hr class={styles.separator} />

        {/* Layout & size */}
        {(["density", "fontSize", "radiusScale"] as const).map((key) => {
          const s = SLIDERS[key];
          return (
            <div class={styles.group} key={key}>
              <div class={styles.label}>
                <span>{s.label}</span>
                <span class={styles.value}>{s.format(values[key])}</span>
              </div>
              <input
                type="range"
                class={styles.slider}
                min={s.min}
                max={s.max}
                step={s.step}
                value={values[key]}
                onInput={(e) => handleChange(key, parseFloat((e.target as HTMLInputElement).value))}
              />
            </div>
          );
        })}

        <hr class={styles.separator} />

        {/* Depth */}
        {(["surfaceGap", "shadowIntensity"] as const).map((key) => {
          const s = SLIDERS[key];
          return (
            <div class={styles.group} key={key}>
              <div class={styles.label}>
                <span>{s.label}</span>
                <span class={styles.value}>{s.format(values[key])}</span>
              </div>
              <input
                type="range"
                class={styles.slider}
                min={s.min}
                max={s.max}
                step={s.step}
                value={values[key]}
                onInput={(e) => handleChange(key, parseFloat((e.target as HTMLInputElement).value))}
              />
            </div>
          );
        })}

        <hr class={styles.separator} />
        <button type="button" class={styles.resetBtn} onClick={handleReset}>
          Reset all
        </button>
      </div>
    </div>
  );
}
