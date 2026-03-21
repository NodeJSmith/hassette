import type { Signal } from "@preact/signals";

const FILTERS = ["all", "running", "failed", "stopped", "disabled", "blocked"] as const;
type FilterValue = (typeof FILTERS)[number];

interface Props {
  active: Signal<FilterValue>;
  counts: Record<string, number>;
}

export function StatusFilter({ active, counts }: Props) {
  return (
    <div class="ht-tab-bar">
      {FILTERS.map((f) => {
        const count = f === "all" ? Object.values(counts).reduce((a, b) => a + b, 0) : (counts[f] ?? 0);
        return (
          <button
            key={f}
            class={`ht-tab${active.value === f ? " active" : ""}`}
            onClick={() => { active.value = f; }}
          >
            {f} <span class="ht-tab-count">{count}</span>
          </button>
        );
      })}
    </div>
  );
}

export type { FilterValue };
