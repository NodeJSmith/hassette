import clsx from "clsx";
import { useEffect } from "preact/hooks";

import { useQueryParams } from "../../hooks/use-query-params";
import { useAppState } from "../../state/context";
import type { TimePreset } from "../../state/create-app-state";
import { isTimePreset } from "../../state/create-app-state";
import { formatUptime } from "../../utils/format";
import { setStoredValue } from "../../utils/local-storage";
import styles from "./time-preset-selector.module.css";

const PRESETS: { value: TimePreset; label: string }[] = [
  { value: "since-restart", label: "Since restart" },
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

export function TimePresetSelector() {
  const { timePreset, urlWindowParam, uptimeSeconds } = useAppState();
  const qp = useQueryParams();

  // On mount: read ?window= from URL and write to urlWindowParam (read-only override).
  // Do NOT write to timePreset or localStorage — URL override is additive.
  useEffect(() => {
    const windowParam = qp.get("window");
    if (windowParam !== null && isTimePreset(windowParam)) {
      urlWindowParam.value = windowParam;
    }
  }, []);

  // Derive the displayed active preset: URL override takes priority via effectiveTimePreset,
  // but the button highlight reflects timePreset (the persisted preference).
  // Both are updated together on click so they stay consistent.
  const current = timePreset.value;
  const uptime = uptimeSeconds.value;

  const handlePreset = (value: TimePreset) => {
    // Update localStorage-backed global preference
    timePreset.value = value;
    setStoredValue("timePreset", value);
    // Update the URL override signal so effectiveTimePreset picks it up immediately
    urlWindowParam.value = value;
    // Sync the URL query param (always write — do not conditionally omit)
    qp.set({ window: value });
  };

  return (
    <div class={styles.selector} data-testid="time-preset-selector">
      {PRESETS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          class={clsx(styles.btn, current === value && styles.active)}
          aria-pressed={current === value}
          onClick={() => handlePreset(value)}
        >
          {label}
        </button>
      ))}
      {Number.isFinite(uptime) && <span class={styles.uptime}>up {formatUptime(uptime!)}</span>}
    </div>
  );
}
