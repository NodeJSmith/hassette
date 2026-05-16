import { COLUMN_MAP } from "./constants";
import { rowKey } from "./types";
import { LogTableHeader } from "./log-table-header";
import { LogTableRow } from "./log-table-row";
import type { LogTableViewProps } from "./use-log-table";

export function LogTableView({
  visibleColumns,
  sortConfig,
  onSort,
  columnFilters,
  entries,
  selectedKey,
  onRowClick,
  isMobile,
}: LogTableViewProps) {
  return (
    <table class="ht-table" data-testid="log-table">
      <colgroup>
        {visibleColumns.map((id) => {
          const col = COLUMN_MAP[id];
          const w = isMobile ? col.mobileWidth : col.width;
          return <col key={id} style={w ? { width: w } : undefined} />;
        })}
      </colgroup>
      <LogTableHeader
        visibleColumns={visibleColumns}
        sortConfig={sortConfig}
        onSort={onSort}
        columnFilters={columnFilters}
      />
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
