import { useRef } from "preact/hooks";
import clsx from "clsx";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../../../hooks/use-media-query";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import type { ColumnId, SortColumn, SortConfig, LevelFilter, TierFilter } from "./types";
import { COLUMN_MAP, LEVEL_OPTIONS, DEFAULT_LEVEL, TIER_OPTIONS } from "./constants";
import { ColumnFilterPopover } from "./column-filter";
import filterStyles from "./column-filter.module.css";
import styles from "./log-table-header.module.css";

interface Props {
  visibleColumns: ColumnId[];
  sortConfig: SortConfig;
  onSort: (col: SortColumn) => void;
  level: LevelFilter;
  onLevelChange: (level: LevelFilter) => void;
  tier: TierFilter;
  onTierChange: (tier: TierFilter) => void;
  appFilter: string;
  onAppChange: (app: string) => void;
  appKeys?: string[];
  fnFilter: string;
  onFnChange: (fn: string) => void;
  defaultTier: TierFilter;
}

interface HeaderCellProps {
  columnId: ColumnId;
  sortConfig: SortConfig;
  onSort: (col: SortColumn) => void;
  hasActiveFilter: boolean;
  filterContent: preact.ComponentChildren | null;
}

function HeaderCell({ columnId, sortConfig, onSort, hasActiveFilter, filterContent }: HeaderCellProps) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const col = COLUMN_MAP[columnId];
  const filterOpen = useSignal(false);
  useSubscribe(filterOpen);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const isActive = col.sortKey ? sortConfig.column === col.sortKey : false;
  const direction = isActive ? (sortConfig.asc ? "asc" : "desc") : undefined;
  const displayLabel = isMobile && col.shortLabel ? col.shortLabel : col.label;

  return (
    <th
      scope="col"
      class={clsx(styles.th, col.mono && styles.mono)}
      aria-sort={isActive ? (sortConfig.asc ? "ascending" : "descending") : undefined}
      aria-label={col.ariaLabel}
    >
      <div class={styles.headerInner}>
        {col.sortKey ? (
          <button
            type="button"
            class={clsx(styles.sortBtn, isActive && styles.sortActive)}
            onClick={() => onSort(col.sortKey!)}
            aria-label={`Sort by ${col.ariaLabel}`}
            data-testid={`sort-${col.sortKey}`}
          >
            {displayLabel}
            {isActive && <span class={styles.sortArrow}>{direction === "asc" ? " ↑" : " ↓"}</span>}
          </button>
        ) : (
          <span>{displayLabel}</span>
        )}
        {col.filterable && filterContent && (
          <>
            <button
              ref={triggerRef}
              type="button"
              class={clsx(styles.filterBtn, hasActiveFilter && styles.filterActive)}
              onClick={() => { filterOpen.value = !filterOpen.value; }}
              aria-label={`Filter ${col.ariaLabel}`}
              data-testid={`filter-${columnId}-btn`}
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path d="M1 2h10L7.5 6.5V10L4.5 9V6.5L1 2z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
              </svg>
              {hasActiveFilter && <span class={styles.filterDot} />}
            </button>
            <ColumnFilterPopover open={filterOpen.value} onClose={() => { filterOpen.value = false; }} triggerRef={triggerRef}>
              {filterContent}
            </ColumnFilterPopover>
          </>
        )}
      </div>
    </th>
  );
}

export function LogTableHeader({
  visibleColumns, sortConfig, onSort,
  level, onLevelChange,
  tier, onTierChange,
  appFilter, onAppChange, appKeys,
  fnFilter, onFnChange,
  defaultTier,
}: Props) {
  function filterFor(id: ColumnId): { active: boolean; content: preact.ComponentChildren | null } {
    switch (id) {
      case "level":
        return {
          active: level !== DEFAULT_LEVEL,
          content: (
            <div>
              <div class={filterStyles.heading}>Minimum level</div>
              <select
                value={level}
                onChange={(e) => onLevelChange((e.target as HTMLSelectElement).value as LevelFilter)}
                data-testid="filter-level"
              >
                {LEVEL_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          ),
        };
      case "app":
        return {
          active: tier !== defaultTier || appFilter !== "",
          content: (
            <div>
              <div class={filterStyles.tierGroup}>
                {TIER_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    class={clsx(filterStyles.tierBtn, tier === opt.value && filterStyles.active)}
                    onClick={() => onTierChange(opt.value)}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
              {tier !== "framework" && appKeys && appKeys.length > 0 && (
                <>
                  <div class={filterStyles.heading}>App</div>
                  <select
                    value={appFilter}
                    onChange={(e) => onAppChange((e.target as HTMLSelectElement).value)}
                    data-testid="filter-app"
                  >
                    <option value="">All apps</option>
                    {appKeys.map((key) => (
                      <option key={key} value={key}>{key}</option>
                    ))}
                  </select>
                </>
              )}
            </div>
          ),
        };
      case "function":
        return {
          active: fnFilter !== "",
          content: (
            <div>
              <div class={filterStyles.heading}>Function name</div>
              <input
                type="text"
                value={fnFilter}
                placeholder="Filter..."
                onInput={(e) => onFnChange((e.target as HTMLInputElement).value)}
                data-testid="filter-fn"
              />
            </div>
          ),
        };
      default:
        return { active: false, content: null };
    }
  }

  return (
    <thead class={styles.thead}>
      <tr>
        {visibleColumns.map((id) => {
          const { active, content } = filterFor(id);
          return (
            <HeaderCell
              key={id}
              columnId={id}
              sortConfig={sortConfig}
              onSort={onSort}
              hasActiveFilter={active}
              filterContent={content}
            />
          );
        })}
      </tr>
    </thead>
  );
}
