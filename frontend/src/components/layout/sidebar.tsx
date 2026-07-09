import clsx from "clsx";
import { useState } from "preact/hooks";
import { Link, useLocation, useSearch } from "wouter";

import type { components } from "../../api/generated-types";
import { useManifests } from "../../hooks/use-manifests";
import { useAppState } from "../../state/context";
import { statusToKind } from "../../utils/status";
import { Chip } from "../shared/chip";
import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import styles from "./sidebar.module.css";
import { getGroupKey, GROUP_DEFS, type GroupDef, type GroupKey, worstStatus } from "./sidebar-groups";
import { useGroupOpen } from "./use-group-open";

type AppManifest = components["schemas"]["AppManifestResponse"];

// Up/down accordion chevron — distinct from IconChevron (right/down disclosure pattern).
function SidebarChevron({ open, class: className }: { open: boolean; class?: string }) {
  return (
    <svg class={className} viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
      <polyline points={open ? "2,8 6,4 10,8" : "2,4 6,8 10,4"} fill="none" stroke="currentColor" stroke-width="1.5" />
    </svg>
  );
}

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.userAgent);
const SHORTCUT_HINT = IS_MAC ? "⌘K" : "Ctrl+K";

const NAV_ITEMS = [
  { path: "/apps", label: "apps", testId: "nav-apps" },
  { path: "/handlers", label: "handlers", testId: "nav-handlers" },
  { path: "/logs", label: "logs", testId: "nav-logs" },
  { path: "/config", label: "config", testId: "nav-config" },
  { path: "/diagnostics", label: "diagnostics", testId: "nav-diagnostics" },
] as const;

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
  const appPath = `/apps/${manifest.app_key}`;
  const isActive = location.startsWith(appPath);

  return (
    <li data-testid={`app-entry-${manifest.app_key}`}>
      <div
        class={clsx(styles.appItem, isActive && "is-active", isBlocked && "is-blocked")}
        aria-disabled={isBlocked ? "true" : undefined}
        data-testid={`app-item-${manifest.app_key}`}
      >
        <Link href={appPath} class={styles.appLink} aria-current={isActive ? "page" : undefined} data-testid="app-link">
          <StatusShape kind={kind} size={10} />
          <span class={styles.appName}>{manifest.display_name}</span>
          {manifest.auto_loaded && (
            <Chip variant="muted" title="Auto-loaded">
              auto
            </Chip>
          )}
        </Link>
        {isMulti && (
          <button
            type="button"
            class={styles.appExpand}
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
        <ul class={styles.instanceList} data-testid="instance-list">
          {(manifest.instances ?? []).map((inst) => {
            const instHref = `/apps/${manifest.app_key}?instance=${inst.index}`;
            const pathMatches = location === appPath || location.startsWith(appPath + "/");
            const instanceParam = new URLSearchParams(searchString).get("instance");
            const instActive = pathMatches && instanceParam === String(inst.index);
            return (
              <li key={inst.index} class={styles.instanceItem}>
                <span class={styles.appConnector}>└</span>
                <Link
                  href={instHref}
                  class={clsx(styles.instanceLink, instActive && "is-active")}
                  aria-current={instActive ? "page" : undefined}
                >
                  <StatusShape kind={statusToKind(inst.status)} size={8} />
                  <span class={styles.instanceName}>{inst.instance_name}</span>
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
      class={clsx(styles.groupHeader, {
        [styles.groupHeaderErr]: def.tone === "err",
        [styles.groupHeaderWarn]: def.tone === "warn",
      })}
      data-testid="group-header"
      aria-expanded={isOpen}
      onClick={onToggle}
    >
      <SidebarChevron open={isOpen} class={styles.groupChevron} />
      <StatusShape kind={def.tone} size={7} />
      <span class={styles.groupLabel}>{def.label}</span>
      <span class={styles.groupCount}>{count}</span>
    </button>
  );
}

interface SidebarProps {
  onOpenPalette?: () => void;
}

export function Sidebar({ onOpenPalette }: SidebarProps = {}) {
  const [location] = useLocation();
  const searchString = useSearch();
  const { systemVersion } = useAppState();
  const { data: allManifests = [], isPending: manifestsLoading } = useManifests();
  const [search, setSearch] = useState("");

  const version = systemVersion.value;
  const isFiltering = search.trim().length > 0;
  const filtered = isFiltering
    ? allManifests.filter(
        (m) =>
          m.display_name.toLowerCase().includes(search.toLowerCase()) ||
          m.app_key.toLowerCase().includes(search.toLowerCase()),
      )
    : allManifests;

  // Group apps by status
  const groups = new Map<GroupKey, AppManifest[]>(GROUP_DEFS.map((g) => [g.key, []]));
  for (const m of filtered) {
    const key = getGroupKey(m);
    groups.get(key)!.push(m);
  }

  // Sort each group alphabetically
  for (const [, apps] of groups) {
    apps.sort((a, b) => a.display_name.localeCompare(b.display_name));
  }

  // "All healthy" check: only ok group has apps (force RUNNING open)
  const allHealthy =
    (groups.get("err")?.length ?? 0) === 0 &&
    (groups.get("blocked")?.length ?? 0) === 0 &&
    (groups.get("warn")?.length ?? 0) === 0 &&
    (groups.get("stopped")?.length ?? 0) === 0;

  const { isOpen: isGroupOpen, toggle: toggleGroup } = useGroupOpen(allHealthy);

  const totalCount = allManifests.length;
  const filteredCount = filtered.length;

  return (
    <aside class={styles.sidebar} data-testid="sidebar">
      <div class={styles.sidebarBrand}>
        <Link href="/apps" class={styles.brandLink} aria-label="Hassette home">
          <span class={styles.wordmark}>hassette</span>
        </Link>
        {version !== null && (
          <div class={styles.version}>
            <span class={styles.versionText}>v{version}</span>
          </div>
        )}
      </div>

      <button
        type="button"
        class={styles.cmdkey}
        title={`Command palette (${SHORTCUT_HINT})`}
        aria-label="Open command palette"
        onClick={onOpenPalette}
      >
        <span>jump to…</span>
        <kbd class={styles.cmdkeyHint}>{SHORTCUT_HINT}</kbd>
      </button>

      <nav aria-label="Main navigation">
        <ul class={styles.navList}>
          {NAV_ITEMS.map((item) => {
            const isActive = location.startsWith(item.path);
            return (
              <li key={item.path}>
                <Link
                  href={item.path}
                  class={clsx(styles.navItem, isActive && "is-active")}
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

      <div class={styles.appNav} data-testid="app-nav">
        <div class={styles.sectionHeader}>
          <span class={styles.sectionLabel}>APPS</span>
          <span class={styles.sectionCount}>{isFiltering ? `${filteredCount}/${totalCount}` : totalCount}</span>
        </div>

        <div class={styles.searchWrap}>
          <input
            type="search"
            class={styles.appSearch}
            placeholder="Filter apps…"
            value={search}
            aria-label="Filter apps"
            onInput={(e) => setSearch((e.target as HTMLInputElement).value)}
          />
        </div>

        {manifestsLoading && <Spinner />}
        {!manifestsLoading && filtered.length === 0 && <div class={styles.empty}>no apps</div>}
        {GROUP_DEFS.map((def) => {
          const apps = groups.get(def.key) ?? [];
          if (apps.length === 0) return null;
          const open = isGroupOpen(def.key);
          return (
            <div key={def.key} class={styles.group}>
              <StatusGroupHeader def={def} count={apps.length} isOpen={open} onToggle={() => toggleGroup(def.key)} />
              {open && (
                <ul class={styles.appList} aria-label={`${def.label} apps`}>
                  {apps.map((m) => (
                    <AppEntry key={m.app_key} manifest={m} location={location} searchString={searchString} />
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}
