import { useAppState } from "../../state/context";
import type { TimePreset } from "../../state/create-app-state";
import { setStoredValue } from "../../utils/local-storage";

const PRESETS: { value: TimePreset; label: string }[] = [
  { value: "since-restart", label: "Since restart" },
  { value: "1h", label: "1h" },
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
];

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

export function TimePresetSelector() {
  const { timePreset, uptimeSeconds } = useAppState();
  const current = timePreset.value;
  const uptime = uptimeSeconds.value;

  const handlePreset = (value: TimePreset) => {
    timePreset.value = value;
    setStoredValue("timePreset", value);
  };

  return (
    <div class="time-preset-selector">
      {PRESETS.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          class={`time-preset-selector__btn${current === value ? " is-active" : ""}`}
          aria-pressed={current === value}
          onClick={() => handlePreset(value)}
        >
          {label}
        </button>
      ))}
      {Number.isFinite(uptime) && uptime !== null && (
        <span class="time-preset-selector__uptime">
          up {formatUptime(uptime as number)}
        </span>
      )}
    </div>
  );
}
