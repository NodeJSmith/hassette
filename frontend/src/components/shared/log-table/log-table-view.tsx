import { useRovingTabIndex } from "../../../hooks/use-roving-tab-index";
import { COLUMN_MAP } from "./constants";
import { LogTableHeader } from "./log-table-header";
import { LogTableRow } from "./log-table-row";
import { rowKey } from "./types";
import type { LogTableViewProps } from "./use-log-table";

export function LogTableView({
  visibleColumns,
  sort,
  onSort,
  columnFilters,
  entries,
  selectedKey,
  onRowClick,
  isMobile,
}: LogTableViewProps) {
  const { containerRef, onContainerKeyDown, getTabIndex, setActiveIndex } = useRovingTabIndex<HTMLTableSectionElement>(
    entries.length,
  );

  return (
    <table class="ht-table ht-table--fixed" data-testid="log-table">
      <colgroup>
        {visibleColumns.map((id) => {
          const col = COLUMN_MAP[id];
          const w = isMobile ? col.mobileWidth : col.width;
          return <col key={id} style={w ? { width: w } : undefined} />;
        })}
      </colgroup>
      <LogTableHeader visibleColumns={visibleColumns} sort={sort} onSort={onSort} columnFilters={columnFilters} />
      <tbody ref={containerRef} onKeyDown={onContainerKeyDown}>
        {entries.map((entry, i) => {
          const key = rowKey(entry);
          return (
            <LogTableRow
              key={key}
              entry={entry}
              rowKey={key}
              visibleColumns={visibleColumns}
              isSelected={selectedKey === key}
              onClick={() => {
                setActiveIndex(i);
                onRowClick(entry);
              }}
              tabIndex={getTabIndex(i)}
            />
          );
        })}
      </tbody>
    </table>
  );
}
