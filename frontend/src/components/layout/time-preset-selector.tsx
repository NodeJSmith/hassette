import { useAppState } from "../../state/context";
import type { TimePreset } from "../../state/create-app-state";
import { setStoredValue } from "../../utils/local-storage";
import { formatUptime } from "../../utils/format";

const PRESETS: { value: TimePreset; label: string }[] = [
  { value: "since-restart", label: "Since restart" },
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

export function TimePresetSelector() {
  const { timePreset, uptimeSeconds } = useAppState();
  const current = timePreset.value;
  const uptime = uptimeSeconds.value;

  const handlePreset = (value: TimePreset) => {
    timePreset.value = value;
    setStoredValue("timePreset", value);
  };

  return (
    <div class="ht-time-preset-selector">
      {PRESETS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          class={`ht-time-preset-selector__btn${current === value ? " ht-time-preset-selector__btn--active" : ""}`}
          aria-pressed={current === value}
          onClick={() => handlePreset(value)}
        >
          {label}
        </button>
      ))}
      {Number.isFinite(uptime) && (
        <span class="ht-time-preset-selector__uptime">
          up {formatUptime(uptime!)}
        </span>
      )}
    </div>
  );
}
