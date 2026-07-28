import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { LogDetailDrawer } from "./log-detail-drawer";
import type { LogDrawerProps } from "./use-log-table";

interface Props {
  drawerProps: LogDrawerProps;
  children: ReactNode;
}

export function LogTableWithDrawer({ drawerProps, children }: Props) {
  const open = drawerProps.selectedKey !== null;
  return (
    <div
      className={cn(
        "grid grid-cols-1 transition-[grid-template-columns] duration-[var(--t-med)] ease-[var(--ease)]",
        open && "grid-cols-[1fr_var(--size-drawer)] max-tablet:grid-cols-1",
      )}
      data-testid="log-table-with-drawer"
    >
      <div className="min-w-0" data-testid="log-table-drawer-table-area">
        {children}
      </div>
      <LogDetailDrawer
        selectedKey={drawerProps.selectedKey}
        entries={drawerProps.entries}
        onClose={drawerProps.onClose}
        onNavigate={drawerProps.onNavigate}
      />
    </div>
  );
}
