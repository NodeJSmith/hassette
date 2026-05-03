import { useState } from "preact/hooks";
import { Link, useLocation } from "wouter";
import { getManifests } from "../../api/endpoints";
import { useApi } from "../../hooks/use-api";
import { useAppState } from "../../state/context";
import { statusToKind } from "../../utils/status";
import { StatusShape } from "../shared/status-shape";
import type { components } from "../../api/generated-types";

type AppManifest = components["schemas"]["AppManifestResponse"];

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.userAgent);

/** Status sort priority: failing first, disabled/not_started last. */
const STATUS_ORDER: Record<string, number> = {
  failed: 0,
  crashed: 0,
  exhausted_dead: 0,
  blocked: 1,
  exhausted_cooling: 2,
  starting: 2,
  running: 3,
  stopping: 4,
  shutting_down: 4,
  stopped: 5,
  disabled: 6,
  not_started: 7,
};

function statusSortKey(status: string): number {
  return STATUS_ORDER[status] ?? 4;
}

/** Return the worst-of-children status for a multi-instance app. */
function worstStatus(manifests: AppManifest): string {
  const instances = manifests.instances ?? [];
  if (instances.length === 0) return manifests.status;
  return instances.reduce((worst, inst) => {
    return statusSortKey(inst.status) < statusSortKey(worst) ? inst.status : worst;
  }, manifests.status);
}

const NAV_ITEMS = [
  { path: "/", label: "Overview", testId: "nav-overview" },
  { path: "/logs", label: "Logs", testId: "nav-logs" },
  { path: "/config", label: "Config", testId: "nav-config" },
] as const;

interface AppEntryProps {
  manifest: AppManifest;
  location: string;
}

function AppEntry({ manifest, location }: AppEntryProps) {
  const [expanded, setExpanded] = useState(false);
  const isMulti = manifest.instance_count > 1;
  const displayStatus = isMulti ? worstStatus(manifest) : manifest.status;
  const kind = statusToKind(displayStatus);
  const isBlocked = manifest.status === "blocked";

  // Active when on any sub-path of this app
  const appPath = `/apps/${manifest.app_key}`;
  const isActive = location.startsWith(appPath);

  return (
    <li class="ht-sidebar__app-entry">
      <div class={`ht-sidebar__app-item${isActive ? " is-active" : ""}${isBlocked ? " is-blocked" : ""}`}>
        <Link
          href={appPath}
          class="ht-sidebar__app-link"
          aria-current={isActive ? "page" : undefined}
        >
          <StatusShape kind={kind} size={10} />
          <span class="ht-sidebar__app-name">{manifest.display_name}</span>
          {manifest.auto_loaded && (
            <span class="ht-sidebar__auto-badge" title="Auto-loaded">auto</span>
          )}
        </Link>
        {isMulti && (
          <button
            type="button"
            class="ht-sidebar__app-expand"
            aria-label={expanded ? `Collapse ${manifest.display_name}` : `Expand ${manifest.display_name}`}
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
              <polyline
                points={expanded ? "2,8 6,4 10,8" : "2,4 6,8 10,4"}
                fill="none"
                stroke="currentColor"
                stroke-width="1.5"
              />
            </svg>
          </button>
        )}
      </div>
      {isMulti && expanded && (
        <ul class="ht-sidebar__instance-list">
          {(manifest.instances ?? []).map((inst) => {
            const instPath = `/apps/${manifest.app_key}/${inst.index}`;
            const instActive = location === instPath || location.startsWith(instPath + "/");
            return (
              <li key={inst.index} class="ht-sidebar__instance-item">
                <span class="ht-sidebar__app-connector">└</span>
                <Link
                  href={instPath}
                  class={`ht-sidebar__instance-link${instActive ? " is-active" : ""}`}
                  aria-current={instActive ? "page" : undefined}
                >
                  <StatusShape kind={statusToKind(inst.status)} size={8} />
                  <span class="ht-sidebar__instance-name">{inst.instance_name}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

interface SidebarProps {
  onOpenPalette?: () => void;
}

export function Sidebar({ onOpenPalette }: SidebarProps = {}) {
  const [location] = useLocation();
  const { connection } = useAppState();
  const manifests = useApi(getManifests);
  const [search, setSearch] = useState("");

  const wsStatus = connection.value;
  const wsKind = wsStatus === "connected" ? "ok"
    : wsStatus === "connecting" ? "mute"
    : "warn";

  const allManifests = manifests.data.value?.manifests ?? [];
  const filtered = search.trim()
    ? allManifests.filter((m) =>
        m.display_name.toLowerCase().includes(search.toLowerCase()) ||
        m.app_key.toLowerCase().includes(search.toLowerCase()),
      )
    : allManifests;

  // Sort by status priority, then alphabetically
  const sorted = [...filtered].sort((a, b) => {
    const aKey = isMultiInstance(a) ? statusSortKey(worstStatus(a)) : statusSortKey(a.status);
    const bKey = isMultiInstance(b) ? statusSortKey(worstStatus(b)) : statusSortKey(b.status);
    if (aKey !== bKey) return aKey - bKey;
    return a.display_name.localeCompare(b.display_name);
  });

  return (
    <aside class="ht-sidebar">
      {/* Wordmark */}
      <div class="ht-sidebar-brand">
        <Link href="/" class="ht-brand-link" aria-label="Hassette home">
          <span class="ht-wordmark">hassette</span>
        </Link>
      </div>

      {/* Connection status */}
      <div class="ht-sidebar__ws-status" aria-label={`WebSocket: ${wsStatus}`}>
        <StatusShape kind={wsKind} size={8} />
        <span class="ht-sidebar__ws-label">{wsStatus}</span>
      </div>

      {/* Cmd-K trigger */}
      <button
        type="button"
        class="ht-sidebar__cmdkey"
        title={`Command palette (${IS_MAC ? "⌘K" : "Ctrl+K"})`}
        aria-label="Open command palette"
        onClick={onOpenPalette}
      >
        <span>Search</span>
        <kbd class="ht-sidebar__cmdkey-hint">{IS_MAC ? "⌘K" : "Ctrl+K"}</kbd>
      </button>

      {/* Top-level navigation */}
      <nav aria-label="Main navigation">
        <ul class="ht-nav-list">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.path === "/" ? location === "/" : location.startsWith(item.path);
            return (
              <li key={item.path}>
                <Link
                  href={item.path}
                  class={`ht-nav-item${isActive ? " is-active" : ""}`}
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

      {/* App search + list */}
      <div class="ht-sidebar__app-nav">
        <div class="ht-sidebar__search-wrap">
          <input
            type="search"
            class="ht-sidebar__app-search"
            placeholder="Filter apps…"
            value={search}
            aria-label="Filter apps"
            onInput={(e) => setSearch((e.target as HTMLInputElement).value)}
          />
        </div>

        <ul class="ht-sidebar__app-list" aria-label="App list">
          {manifests.loading.value && (
            <li class="ht-sidebar__loading">Loading…</li>
          )}
          {!manifests.loading.value && sorted.length === 0 && (
            <li class="ht-sidebar__empty">No apps</li>
          )}
          {sorted.map((m) => (
            <AppEntry key={m.app_key} manifest={m} location={location} />
          ))}
        </ul>
      </div>
    </aside>
  );
}

function isMultiInstance(m: AppManifest): boolean {
  return m.instance_count > 1;
}
