import type { RefObject } from "react";

import { Button } from "@/components/ui/button";

import { useBreadcrumbs } from "../../hooks/use-breadcrumbs";
import { useSidebarHidden } from "../../hooks/use-sidebar-hidden";
import { useAppStore } from "../../state/store";
import { Breadcrumbs } from "../shared/breadcrumbs";
import { IconChevronRight, IconMenu } from "../shared/icons";
import { SystemHealth } from "../shared/system-health";
import { ThemeToggle } from "../shared/theme-toggle";
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
    <div
      className="sticky top-0 z-[var(--z-status-bar-layer)] flex shrink-0 items-center justify-between gap-3 border-b border-border bg-[var(--bg-chrome)] px-8 py-2 max-mobile:gap-2 max-mobile:px-3"
      data-testid="status-bar"
      {...(drawerOpen ? { inert: true } : {})}
    >
      <div className="flex min-w-[var(--size-touch)] flex-1 items-center gap-3 overflow-hidden max-mobile:gap-2">
        <Button
          ref={hamburgerRef}
          variant="subtle"
          size="icon"
          touch
          className="hidden max-sidebar:flex"
          aria-label="Open navigation"
          aria-expanded={drawerOpen}
          data-testid="hamburger"
          onClick={onMenuClick}
        >
          <IconMenu />
        </Button>

        {/* Collapsing unmounts the sidebar, so this is the only way back to it. */}
        {sidebarCollapsed && (
          <Button
            variant="ghost"
            size="icon-sm"
            className="max-sidebar:hidden"
            title="Expand sidebar ([)"
            aria-label="Expand sidebar"
            data-testid="sidebar-expand"
            onClick={() => {
              setSidebarCollapsed(false);
            }}
          >
            <IconChevronRight />
          </Button>
        )}

        <Breadcrumbs items={crumbs} />
      </div>

      {/* Both of these live in the sidebar footer when it is on screen. Collapsing unmounts
          the sidebar outright, so without this fallback the theme toggle would have no
          reachable home on desktop at all. */}
      <div className="flex shrink-0 items-center gap-3 max-mobile:gap-1.5">
        {sidebarHidden && <SystemHealth variant="compact" />}
        <TimePresetSelector />
        {sidebarHidden && <ThemeToggle />}
      </div>
    </div>
  );
}
