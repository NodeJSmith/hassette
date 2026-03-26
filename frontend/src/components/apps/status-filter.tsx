import type { Signal } from "@preact/signals";

const FILTERS = ["all", "running", "failed", "stopped", "disabled"] as const;
type FilterValue = (typeof FILTERS)[number];

interface Props {
  active: Signal<FilterValue>;
  counts: Record<string, number>;
}

export function StatusFilter({ active, counts }: Props) {
  return (
    <div class="ht-tabs" role="group" aria-label="App status filter">
      <ul>
        {FILTERS.map((f) => {
          const count = f === "all" ? Object.values(counts).reduce((a, b) => a + b, 0) : (counts[f] ?? 0);
          return (
            <li key={f} data-testid={`tab-${f}`}>
              <button
                type="button"
                aria-pressed={active.value === f}
                onClick={() => { active.value = f; }}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)} ({count})
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export type { FilterValue };
