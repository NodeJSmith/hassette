import clsx from "clsx";
import { useEffect } from "preact/hooks";

import { BREAKPOINT_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
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
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  useEffect(() => {
    const windowParam = qp.get("window");
    if (windowParam !== null && isTimePreset(windowParam)) {
      urlWindowParam.value = windowParam;
    } else {
      urlWindowParam.value = null;
    }
  }, []);

  const current = timePreset.value;
  const uptime = uptimeSeconds.value;
  const showUptime = uptime !== null && Number.isFinite(uptime);

  const handlePreset = (value: TimePreset) => {
    timePreset.value = value;
    setStoredValue("timePreset", value);
    urlWindowParam.value = value;
    qp.set({ window: value });
  };

  if (isMobile) {
    return (
      <div class={styles.selector} data-testid="time-preset-selector">
        <select
          class={styles.select}
          value={current}
          onChange={(e) => handlePreset((e.target as HTMLSelectElement).value as TimePreset)}
          aria-label="Time window"
        >
          {PRESETS.map(({ value, label }) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        {showUptime && <span class={styles.uptime}>up {formatUptime(uptime)}</span>}
      </div>
    );
  }

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
      {showUptime && <span class={styles.uptime}>up {formatUptime(uptime)}</span>}
    </div>
  );
}
