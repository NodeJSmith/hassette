import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

import { LogDetailDrawer } from "./log-detail-drawer";
import styles from "./log-table.module.css";
import type { LogDrawerProps } from "./use-log-table";

interface Props {
  drawerProps: LogDrawerProps;
  children: ReactNode;
}

export function LogTableWithDrawer({ drawerProps, children }: Props) {
  const open = drawerProps.selectedKey !== null;
  return (
    <div className={cn(styles.wrapper, open && styles.drawerOpen)}>
      <div className={styles.tableArea}>{children}</div>
      <LogDetailDrawer
        selectedKey={drawerProps.selectedKey}
        entries={drawerProps.entries}
        onClose={drawerProps.onClose}
        onNavigate={drawerProps.onNavigate}
      />
    </div>
  );
}
