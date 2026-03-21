import type { Signal } from "@preact/signals";

const FILTERS = ["all", "running", "failed", "stopped", "disabled"] as const;
type FilterValue = (typeof FILTERS)[number];

interface Props {
  active: Signal<FilterValue>;
  counts: Record<string, number>;
}

export function StatusFilter({ active, counts }: Props) {
  return (
    <nav class="ht-tabs">
      <ul>
        {FILTERS.map((f) => {
          const count = f === "all" ? Object.values(counts).reduce((a, b) => a + b, 0) : (counts[f] ?? 0);
          return (
            <li key={f} class={active.value === f ? "is-active" : ""} data-testid={`tab-${f}`}>
              <a
                href="#"
                onClick={(e) => { e.preventDefault(); active.value = f; }}
              >
                {f.charAt(0).toUpperCase() + f.slice(1)} ({count})
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export type { FilterValue };
