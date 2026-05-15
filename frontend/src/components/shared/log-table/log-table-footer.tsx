import { useRef } from "preact/hooks";
import clsx from "clsx";
import { useMediaQuery, BREAKPOINT_MOBILE } from "../../../hooks/use-media-query";
import { useSignal } from "../../../hooks/use-signal";
import { useSubscribe } from "../../../hooks/use-subscribe";
import { pluralize } from "../../../utils/format";
import type { ColumnId, LevelFilter, TierFilter } from "./types";
import { RENDER_CAP, LEVEL_OPTIONS, TIER_OPTIONS } from "./constants";
import { ColumnPicker } from "./column-picker";
import { ColumnFilterPopover } from "./column-filter";
import filterStyles from "./column-filter.module.css";
import styles from "./log-table-footer.module.css";

interface Props {
  totalCount: number;
  livePaused: boolean;
  onResume: () => void;
  search: string;
  onSearchChange: (value: string) => void;
  selectedColumns: ColumnId[];
  viewportHidden: ReadonlySet<ColumnId>;
  onToggleColumn: (id: ColumnId) => void;
  onResetColumns: () => void;
  level: LevelFilter;
  onLevelChange: (level: LevelFilter) => void;
  tier: TierFilter;
  onTierChange: (tier: TierFilter) => void;
  appFilter: string;
  onAppChange: (app: string) => void;
  appKeys?: string[];
  fnFilter: string;
  onFnChange: (fn: string) => void;
  hasActiveFilter: boolean;
  onResetFilters: () => void;
}

export function LogTableFooter({
  totalCount, livePaused, onResume,
  search, onSearchChange,
  selectedColumns, viewportHidden, onToggleColumn, onResetColumns,
  level, onLevelChange,
  tier, onTierChange,
  appFilter, onAppChange, appKeys,
  fnFilter, onFnChange,
  hasActiveFilter,
  onResetFilters,
}: Props) {
  const isMobile = useMediaQuery(BREAKPOINT_MOBILE);
  const isTruncated = totalCount > RENDER_CAP;
  const countLabel = isTruncated
    ? `showing ${RENDER_CAP} of ${totalCount}`
    : pluralize(totalCount, "entry", "entries");

  const filterOpen = useSignal(false);
  useSubscribe(filterOpen);
  const filterTriggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div class={styles.footer}>
      <div class={styles.left}>
        <span class={styles.count} aria-live="polite">{countLabel}</span>
        {livePaused && (
          <button
            type="button"
            class={styles.pausedBtn}
            onClick={onResume}
            aria-label="Resume live log streaming"
          >
            <span class={styles.pausedDot} />
            paused — click to resume
          </button>
        )}
      </div>
      <div class={styles.right}>
        <input
          class={styles.search}
          type="text"
          aria-label="Search logs"
          placeholder="Search..."
          value={search}
          onInput={(e) => onSearchChange((e.target as HTMLInputElement).value)}
        />
        {isMobile && (
          <>
            <button
              ref={filterTriggerRef}
              type="button"
              class={clsx(styles.filterBtn, hasActiveFilter && styles.filterBtnActive)}
              onClick={() => { filterOpen.value = !filterOpen.value; }}
              aria-label="Open filters"
              data-testid="mobile-filters-btn"
            >
              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
                <path d="M1 2h10L7.5 6.5V10L4.5 9V6.5L1 2z" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round" />
              </svg>
              {hasActiveFilter && <span class={styles.filterDot} />}
            </button>
            <ColumnFilterPopover open={filterOpen.value} onClose={() => { filterOpen.value = false; }} triggerRef={filterTriggerRef}>
              <div class={styles.mobileFilters}>
                <div class={styles.mobileFilterGroup}>
                  <label>Level</label>
                  <select
                    value={level}
                    onChange={(e) => onLevelChange((e.target as HTMLSelectElement).value as LevelFilter)}
                    data-testid="mobile-filter-level"
                  >
                    {LEVEL_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
                <div class={styles.mobileFilterGroup}>
                  <label>Source</label>
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
                </div>
                {tier !== "framework" && appKeys && appKeys.length > 0 && (
                  <div class={styles.mobileFilterGroup}>
                    <label>App</label>
                    <select
                      value={appFilter}
                      onChange={(e) => onAppChange((e.target as HTMLSelectElement).value)}
                      data-testid="mobile-filter-app"
                    >
                      <option value="">All apps</option>
                      {appKeys.map((key) => (
                        <option key={key} value={key}>{key}</option>
                      ))}
                    </select>
                  </div>
                )}
                <div class={styles.mobileFilterGroup}>
                  <label>Function</label>
                  <input
                    type="text"
                    value={fnFilter}
                    placeholder="Filter by function..."
                    onInput={(e) => onFnChange((e.target as HTMLInputElement).value)}
                    data-testid="mobile-filter-fn"
                  />
                </div>
                {hasActiveFilter && (
                  <button
                    type="button"
                    class={styles.resetFiltersBtn}
                    onClick={onResetFilters}
                  >
                    Reset to defaults
                  </button>
                )}
              </div>
            </ColumnFilterPopover>
          </>
        )}
        {!isMobile && (
          <ColumnPicker
            selectedColumns={selectedColumns}
            viewportHidden={viewportHidden}
            onToggle={onToggleColumn}
            onReset={onResetColumns}
          />
        )}
      </div>
    </div>
  );
}
