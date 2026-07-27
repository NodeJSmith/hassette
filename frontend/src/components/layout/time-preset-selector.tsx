import clsx from "clsx";
import { useEffect } from "react";

import { BREAKPOINT_MOBILE, useMediaQuery } from "../../hooks/use-media-query";
import { useQueryParams } from "../../hooks/use-query-params";
import type { TimePreset } from "../../state/store";
import { isTimePreset, useAppStore } from "../../state/store";
import { formatUptime } from "../../utils/format";
import styles from "./time-preset-selector.module.css";

const PRESETS: { value: TimePreset; label: string }[] = [
  { value: "since-restart", label: "Since restart" },
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

export function TimePresetSelector() {
  const timePreset = useAppStore((s) => s.timePreset);
  const setTimePreset = useAppStore((s) => s.setTimePreset);
  const uptimeSeconds = useAppStore((s) => s.uptimeSeconds);
  const setUrlWindowParam = useAppStore((s) => s.setUrlWindowParam);
  const qp = useQueryParams();
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);

  useEffect(() => {
    const windowParam = qp.get("window");
    if (windowParam !== null && isTimePreset(windowParam)) {
      setUrlWindowParam(windowParam);
    } else {
      setUrlWindowParam(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only; qp/setUrlWindowParam are stable
  }, []);

  const current = timePreset;
  const uptime = uptimeSeconds;
  const showUptime = uptime !== null && Number.isFinite(uptime);

  const handlePreset = (value: TimePreset) => {
    setTimePreset(value);
    setUrlWindowParam(value);
    qp.set({ window: value });
  };

  if (isMobile) {
    return (
      <div className={styles.selector} data-testid="time-preset-selector">
        <select
          className={styles.select}
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
        {showUptime && <span className={styles.uptime}>up {formatUptime(uptime)}</span>}
      </div>
    );
  }

  return (
    <div className={styles.selector} data-testid="time-preset-selector">
      {PRESETS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          className={clsx(styles.btn, current === value && styles.active)}
          aria-pressed={current === value}
          onClick={() => handlePreset(value)}
        >
          {label}
        </button>
      ))}
      {showUptime && <span className={styles.uptime}>up {formatUptime(uptime)}</span>}
    </div>
  );
}
