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
      <tbody>
        {entries.map((entry) => {
          const key = rowKey(entry);
          return (
            <LogTableRow
              key={key}
              entry={entry}
              rowKey={key}
              visibleColumns={visibleColumns}
              isSelected={selectedKey === key}
              onClick={() => onRowClick(entry)}
            />
          );
        })}
      </tbody>
    </table>
  );
}
