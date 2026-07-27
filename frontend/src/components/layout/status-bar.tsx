import type { RefObject } from "react";

import { useBreadcrumbs } from "../../hooks/use-breadcrumbs";
import { useSidebarHidden } from "../../hooks/use-sidebar-hidden";
import { useAppStore } from "../../state/store";
import { setStoredValue } from "../../utils/local-storage";
import { Breadcrumbs } from "../shared/breadcrumbs";
import { Button } from "../shared/button";
import { SystemHealth } from "../shared/system-health";
import { ThemeToggle } from "../shared/theme-toggle";
import styles from "./status-bar.module.css";
import { TimePresetSelector } from "./time-preset-selector";

interface StatusBarProps {
  onMenuClick: () => void;
  drawerOpen: boolean;
  hamburgerRef: RefObject<HTMLButtonElement | null>;
}

export function StatusBar({ onMenuClick, drawerOpen, hamburgerRef }: StatusBarProps) {
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const setSidebarCollapsed = useAppStore((s) => s.setSidebarCollapsed);
  const crumbs = useBreadcrumbs();
  const sidebarHidden = useSidebarHidden();

  return (
    <div className={styles.statusBar} data-testid="status-bar">
      <div className={styles.statusBarLeft}>
        <button
          ref={hamburgerRef}
          type="button"
          className={styles.hamburger}
          aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={drawerOpen}
          data-testid="hamburger"
          onClick={onMenuClick}
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>

        {/* Collapsing unmounts the sidebar, so this is the only way back to it. */}
        {sidebarCollapsed && (
          <Button
            icon
            ghost
            size="sm"
            className={styles.expandSidebar}
            title="Expand sidebar ([)"
            aria-label="Expand sidebar"
            data-testid="sidebar-expand"
            onClick={() => {
              setSidebarCollapsed(false);
              setStoredValue("sidebarCollapsed", false);
            }}
          >
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <polyline points="6,3 11,8 6,13" fill="none" stroke="currentColor" stroke-width="1.5" />
            </svg>
          </Button>
        )}

        <Breadcrumbs items={crumbs} />
      </div>

      {/* Both of these live in the sidebar footer when it is on screen. Collapsing unmounts
          the sidebar outright, so without this fallback the theme toggle would have no
          reachable home on desktop at all. */}
      <div className={styles.statusBarRight}>
        {sidebarHidden && <SystemHealth variant="compact" />}
        <TimePresetSelector />
        {sidebarHidden && <ThemeToggle />}
      </div>
    </div>
  );
}
