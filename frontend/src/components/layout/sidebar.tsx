import clsx from "clsx";
import { useState } from "react";
import { Link, useLocation, useSearch } from "wouter";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import type { components } from "../../api/generated-types";
import { useManifests } from "../../hooks/use-manifests";
import { useSidebarHidden } from "../../hooks/use-sidebar-hidden";
import { useAppStore } from "../../state/store";
import { appDetailPath, HOME_PATH, NAV_PAGES } from "../../utils/app-routes";
import { STATUS_DOT_SIZE } from "../../utils/constants";
import { SHORTCUT_HINT } from "../../utils/keyboard";
import { statusToKind } from "../../utils/status";
import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import { SystemHealth } from "../shared/system-health";
import { ThemeToggle } from "../shared/theme-toggle";
import styles from "./sidebar.module.css";
import { GROUP_DEFS, groupAndSortApps, type GroupDef, worstStatus } from "./sidebar-groups";
import { useGroupOpen } from "./use-group-open";

type AppManifest = components["schemas"]["AppManifestResponse"];

// Up/down accordion chevron — distinct from IconChevron (right/down disclosure pattern).
function SidebarChevron({ open, className }: { open: boolean; className?: string }) {
  return (
    <svg className={className} viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
      <polyline points={open ? "2,8 6,4 10,8" : "2,4 6,8 10,4"} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

interface AppEntryProps {
  manifest: AppManifest;
  location: string;
  searchString: string;
}

function AppEntry({ manifest, location, searchString }: AppEntryProps) {
  const [expanded, setExpanded] = useState(false);
  const isMulti = manifest.instance_count > 1;
  const displayStatus = isMulti ? worstStatus(manifest) : manifest.status;
  const kind = statusToKind(displayStatus);
  const isBlocked = displayStatus === "blocked";

  // Active when on any sub-path of this app
  const appPath = appDetailPath(manifest.app_key);
  const isActive = location.startsWith(appPath);

  return (
    <li data-testid={`app-entry-${manifest.app_key}`}>
      <div
        className={clsx(styles.appItem, isActive && "is-active", isBlocked && "is-blocked")}
        aria-disabled={isBlocked ? "true" : undefined}
        data-testid={`app-item-${manifest.app_key}`}
      >
        <Link
          href={appPath}
          className={styles.appLink}
          aria-current={isActive ? "page" : undefined}
          data-testid="app-link"
        >
          <StatusShape kind={kind} size={STATUS_DOT_SIZE} />
          <span className={styles.appName}>{manifest.display_name}</span>
          {manifest.auto_loaded && (
            <Badge variant="muted" title="Auto-loaded">
              auto
            </Badge>
          )}
        </Link>
        {isMulti && (
          <button
            type="button"
            className={styles.appExpand}
            aria-label={expanded ? `Collapse ${manifest.display_name}` : `Expand ${manifest.display_name}`}
            aria-expanded={expanded}
            data-testid="app-expand"
            onClick={() => setExpanded(!expanded)}
          >
            <SidebarChevron open={expanded} />
          </button>
        )}
      </div>
      {isMulti && expanded && (
        <ul className={styles.instanceList} data-testid="instance-list">
          {(manifest.instances ?? []).map((inst) => {
            const instHref = appDetailPath(manifest.app_key, undefined, { instance: inst.index });
            const pathMatches = location === appPath || location.startsWith(appPath + "/");
            const instanceParam = new URLSearchParams(searchString).get("instance");
            const instActive = pathMatches && instanceParam === String(inst.index);
            return (
              <li key={inst.index} className={styles.instanceItem}>
                <span className={styles.appConnector}>└</span>
                <Link
                  href={instHref}
                  className={clsx(styles.instanceLink, instActive && "is-active")}
                  aria-current={instActive ? "page" : undefined}
                >
                  <StatusShape kind={statusToKind(inst.status)} size={8} />
                  <span className={styles.instanceName}>{inst.instance_name}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

interface StatusGroupHeaderProps {
  def: GroupDef;
  count: number;
  isOpen: boolean;
  onToggle: () => void;
}

function StatusGroupHeader({ def, count, isOpen, onToggle }: StatusGroupHeaderProps) {
  return (
    <button
      type="button"
      className={clsx(styles.groupHeader, {
        [styles.groupHeaderErr]: def.tone === "err",
        [styles.groupHeaderWarn]: def.tone === "warn",
      })}
      data-testid="group-header"
      aria-expanded={isOpen}
      onClick={onToggle}
    >
      <SidebarChevron open={isOpen} className={styles.groupChevron} />
      <StatusShape kind={def.tone} size={7} />
      <span className={styles.groupLabel}>{def.label}</span>
      <span className={styles.groupCount}>{count}</span>
    </button>
  );
}

interface SidebarProps {
  onOpenPalette?: () => void;
}

export function Sidebar({ onOpenPalette }: SidebarProps = {}) {
  const [location] = useLocation();
  const searchString = useSearch();
  const systemVersion = useAppStore((s) => s.systemVersion);
  const setSidebarCollapsed = useAppStore((s) => s.setSidebarCollapsed);
  // When the sidebar is off screen the status bar owns this chrome instead; rendering it in
  // both places would duplicate the testids and give screen readers two live regions for
  // one connection event.
  const chromeLivesInStatusBar = useSidebarHidden();
  const { data: manifestsData = [], isPending: manifestsLoading } = useManifests();
  // Removed apps (in_current_config: false) are historical/DB-only — they belong on the
  // apps page (which badges them explicitly), not in primary navigation where they'd be
  // indistinguishable from live apps.
  const liveManifests = manifestsData.filter((m) => m.in_current_config);
  const [search, setSearch] = useState("");

  const version = systemVersion;
  const isFiltering = search.trim().length > 0;
  const filtered = isFiltering
    ? liveManifests.filter(
        (m) =>
          m.display_name.toLowerCase().includes(search.toLowerCase()) ||
          m.app_key.toLowerCase().includes(search.toLowerCase()),
      )
    : liveManifests;

  const { groups, allHealthy } = groupAndSortApps(filtered);

  const { isOpen: isGroupOpen, toggle: toggleGroup } = useGroupOpen(allHealthy);

  const totalCount = liveManifests.length;
  const filteredCount = filtered.length;

  return (
    <aside className={styles.sidebar} data-testid="sidebar">
      <div className={styles.sidebarBrand}>
        <div className={styles.brandText}>
          <Link href={HOME_PATH} className={styles.brandLink} aria-label="Hassette home">
            <span className={styles.wordmark}>hassette</span>
          </Link>
          {version !== null && (
            <div className={styles.version}>
              <span className={styles.versionText}>v{version}</span>
            </div>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          className={styles.collapseToggle}
          title="Collapse sidebar ([)"
          aria-label="Collapse sidebar"
          data-testid="sidebar-collapse"
          onClick={() => {
            setSidebarCollapsed(true);
          }}
        >
          <svg viewBox="0 0 16 16" aria-hidden="true">
            <polyline points="10,3 5,8 10,13" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
        </Button>
      </div>

      <button
        type="button"
        className={styles.cmdkey}
        title={`Command palette (${SHORTCUT_HINT})`}
        aria-label="Open command palette"
        onClick={onOpenPalette}
      >
        <span>jump to…</span>
        <kbd className={styles.cmdkeyHint}>{SHORTCUT_HINT}</kbd>
      </button>

      <nav aria-label="Main navigation">
        <ul className={styles.navList}>
          {NAV_PAGES.map((item) => {
            const isActive = location.startsWith(item.path);
            return (
              <li key={item.path}>
                <Link
                  href={item.path}
                  className={clsx(styles.navItem, isActive && "is-active")}
                  data-testid={item.testId}
                  aria-current={isActive ? "page" : undefined}
                >
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className={styles.appNav} data-testid="app-nav">
        <div className={styles.sectionHeader}>
          <span className={styles.sectionLabel}>APPS</span>
          <span className={styles.sectionCount}>{isFiltering ? `${filteredCount}/${totalCount}` : totalCount}</span>
        </div>

        <div className={styles.searchWrap}>
          <input
            type="search"
            className={styles.appSearch}
            placeholder="Filter apps…"
            value={search}
            aria-label="Filter apps"
            onInput={(e) => setSearch((e.target as HTMLInputElement).value)}
          />
        </div>

        {manifestsLoading && <Spinner />}
        {!manifestsLoading && filtered.length === 0 && <div className={styles.empty}>no apps</div>}
        {GROUP_DEFS.map((def) => {
          const apps = groups.get(def.key) ?? [];
          if (apps.length === 0) return null;
          const open = isGroupOpen(def.key);
          return (
            <div key={def.key} className={styles.group}>
              <StatusGroupHeader def={def} count={apps.length} isOpen={open} onToggle={() => toggleGroup(def.key)} />
              {open && (
                <ul className={styles.appList} aria-label={`${def.label} apps`}>
                  {apps.map((m) => (
                    <AppEntry key={m.app_key} manifest={m} location={location} searchString={searchString} />
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      {!chromeLivesInStatusBar && (
        <div className={styles.sidebarFooter} data-testid="sidebar-footer">
          <SystemHealth variant="stacked" />
          <ThemeToggle />
        </div>
      )}
    </aside>
  );
}
