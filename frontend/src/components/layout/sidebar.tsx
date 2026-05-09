import { useState } from "preact/hooks";
import { Link, useLocation } from "wouter";
import { getManifests } from "../../api/endpoints";
import { useApi } from "../../hooks/use-api";
import { useAppState } from "../../state/context";
import { statusToKind } from "../../utils/status";
import { Spinner } from "../shared/spinner";
import { StatusShape } from "../shared/status-shape";
import type { components } from "../../api/generated-types";

type AppManifest = components["schemas"]["AppManifestResponse"];

let _isMac: boolean | null = null;
function isMac(): boolean {
  if (_isMac === null) _isMac = /Mac|iPhone|iPad/.test(navigator.userAgent);
  return _isMac;
}

// ──────────────────────────────────────────────────────────────────────────────
// Status group definitions
// ──────────────────────────────────────────────────────────────────────────────

type GroupKey = "err" | "blocked" | "warn" | "ok" | "stopped" | "disabled";

interface GroupDef {
  key: GroupKey;
  label: string;
  tone: "err" | "warn" | "ok" | "mute";
  defaultOpen: boolean;
}

const GROUP_DEFS: GroupDef[] = [
  { key: "err",      label: "FAILING",  tone: "err",  defaultOpen: true  },
  { key: "blocked",  label: "BLOCKED",  tone: "err",  defaultOpen: true  },
  { key: "warn",     label: "SLOW",     tone: "warn", defaultOpen: true  },
  { key: "ok",       label: "RUNNING",  tone: "ok",   defaultOpen: false },
  { key: "stopped",  label: "STOPPED",  tone: "mute", defaultOpen: true  },
  { key: "disabled", label: "DISABLED", tone: "mute", defaultOpen: false },
];

const DEFAULT_GROUP_OPEN: Record<GroupKey, boolean> = Object.fromEntries(
  GROUP_DEFS.map((g) => [g.key, g.defaultOpen]),
) as Record<GroupKey, boolean>;

/** Statuses with warn tone (not ok, not err, but needs attention) */
const WARN_STATUSES = new Set(["exhausted_cooling", "stopping", "shutting_down"]);

/** STATUS_ORDER for worst-of-children resolution (lower = worse) */
const STATUS_ORDER: Record<string, number> = {
  failed: 0,
  crashed: 0,
  exhausted_dead: 0,
  blocked: 1,
  exhausted_cooling: 2,
  starting: 3,
  running: 4,
  stopping: 5,
  shutting_down: 5,
  stopped: 6,
  disabled: 7,
  not_started: 8,
};

function statusSortKey(status: string): number {
  return STATUS_ORDER[status] ?? 99;
}

/** Return the worst-of-children status for a multi-instance app. */
function worstStatus(manifest: AppManifest): string {
  const instances = manifest.instances ?? [];
  if (instances.length === 0) return manifest.status;
  return instances.reduce((worst, inst) => {
    return statusSortKey(inst.status) < statusSortKey(worst) ? inst.status : worst;
  }, manifest.status);
}

function isMultiInstance(m: AppManifest): boolean {
  return m.instance_count > 1;
}

/** Map an app manifest to its group key. Uses worst-of-children for multi-instance. */
function getGroupKey(manifest: AppManifest): GroupKey {
  const status = isMultiInstance(manifest) ? worstStatus(manifest) : manifest.status;

  if (status === "blocked") return "blocked";
  if (status === "disabled") return "disabled";
  if (status === "failed" || status === "crashed" || status === "exhausted_dead") return "err";
  if (WARN_STATUSES.has(status)) return "warn";
  if (status === "stopped" || status === "not_started") return "stopped";
  return "ok";
}

// ──────────────────────────────────────────────────────────────────────────────
// Nav items
// ──────────────────────────────────────────────────────────────────────────────

const NAV_ITEMS = [
  { path: "/", label: "overview", testId: "nav-overview" },
  { path: "/apps", label: "apps", testId: "nav-apps" },
  { path: "/handlers", label: "handlers", testId: "nav-handlers" },
  { path: "/logs", label: "logs", testId: "nav-logs" },
  { path: "/diagnostics", label: "diagnostics", testId: "nav-diagnostics" },
  { path: "/config", label: "config", testId: "nav-config" },
] as const;

// ──────────────────────────────────────────────────────────────────────────────
// AppEntry component
// ──────────────────────────────────────────────────────────────────────────────

interface AppEntryProps {
  manifest: AppManifest;
  location: string;
}

function AppEntry({ manifest, location }: AppEntryProps) {
  const [expanded, setExpanded] = useState(false);
  const isMulti = manifest.instance_count > 1;
  const displayStatus = isMulti ? worstStatus(manifest) : manifest.status;
  const kind = statusToKind(displayStatus);
  const isBlocked = displayStatus === "blocked";

  // Active when on any sub-path of this app
  const appPath = `/apps/${manifest.app_key}`;
  const isActive = location.startsWith(appPath);

  const invocationCount = manifest.recent_invocations_1h;

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
            <span class="ht-chip ht-chip--auto" title="Auto-loaded">auto</span>
          )}
          {invocationCount > 0 && (
            <span class="ht-sidebar__app-count">{invocationCount}</span>
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

// ──────────────────────────────────────────────────────────────────────────────
// StatusGroupHeader component
// ──────────────────────────────────────────────────────────────────────────────

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
      class={`ht-sidebar__group-header ht-sidebar__group-header--${def.tone}`}
      aria-expanded={isOpen}
      onClick={onToggle}
    >
      <svg
        class="ht-sidebar__group-chevron"
        viewBox="0 0 12 12"
        width="10"
        height="10"
        aria-hidden="true"
      >
        <polyline
          points={isOpen ? "2,8 6,4 10,8" : "2,4 6,8 10,4"}
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
        />
      </svg>
      <StatusShape kind={def.tone} size={7} />
      <span class="ht-sidebar__group-label">{def.label}</span>
      <span class="ht-sidebar__group-count">{count}</span>
    </button>
  );
}

// ──────────────────────────────────────────────────────────────────────────────
// Sidebar component
// ──────────────────────────────────────────────────────────────────────────────

interface SidebarProps {
  onOpenPalette?: () => void;
}

export function Sidebar({ onOpenPalette }: SidebarProps = {}) {
  const [location] = useLocation();
  const { systemVersion } = useAppState();
  const manifests = useApi(getManifests);
  const [search, setSearch] = useState("");

  const [groupOpen, setGroupOpen] = useState<Record<GroupKey, boolean>>(DEFAULT_GROUP_OPEN);

  const version = systemVersion.value;

  const allManifests = manifests.data.value?.manifests ?? [];
  const isFiltering = search.trim().length > 0;
  const filtered = isFiltering
    ? allManifests.filter((m) =>
        m.display_name.toLowerCase().includes(search.toLowerCase()) ||
        m.app_key.toLowerCase().includes(search.toLowerCase()),
      )
    : allManifests;

  // Group apps by status
  const groups = new Map<GroupKey, AppManifest[]>(
    GROUP_DEFS.map((g) => [g.key, []]),
  );
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

  function isGroupOpen(key: GroupKey): boolean {
    if (key === "ok" && allHealthy) return true; // force open when all healthy
    return groupOpen[key];
  }

  function toggleGroup(key: GroupKey) {
    setGroupOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  const totalCount = allManifests.length;
  const filteredCount = filtered.length;

  return (
    <aside class="ht-sidebar">
      {/* Wordmark */}
      <div class="ht-sidebar-brand">
        <Link href="/" class="ht-brand-link" aria-label="Hassette home">
          <span class="ht-wordmark">hassette</span>
        </Link>
        {version !== null && (
          <div class="ht-sidebar__version">
            <span class="ht-sidebar__version-text">v{version}</span>
          </div>
        )}
      </div>

      {/* Cmd-K trigger */}
      <button
        type="button"
        class="ht-sidebar__cmdkey"
        title={`Command palette (${isMac() ? "⌘K" : "Ctrl+K"})`}
        aria-label="Open command palette"
        onClick={onOpenPalette}
      >
        <span>jump to…</span>
        <kbd class="ht-sidebar__cmdkey-hint">{isMac() ? "⌘K" : "Ctrl+K"}</kbd>
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

      {/* App section */}
      <div class="ht-sidebar__app-nav">
        {/* APPS section header */}
        <div class="ht-sidebar__section-header">
          <span class="ht-sidebar__section-label">APPS</span>
          <span class="ht-sidebar__section-count">
            {isFiltering ? `${filteredCount}/${totalCount}` : totalCount}
          </span>
        </div>

        {/* Search */}
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

        {/* Status groups */}
        {manifests.loading.value && (
          <Spinner />
        )}
        {!manifests.loading.value && filtered.length === 0 && (
          <div class="ht-sidebar__empty">no apps</div>
        )}
        {GROUP_DEFS.map((def) => {
          const apps = groups.get(def.key) ?? [];
          if (apps.length === 0) return null;
          const open = isGroupOpen(def.key);
          return (
            <div key={def.key} class="ht-sidebar__group">
              <StatusGroupHeader
                def={def}
                count={apps.length}
                isOpen={open}
                onToggle={() => toggleGroup(def.key)}
              />
              {open && (
                <ul class="ht-sidebar__app-list" aria-label={`${def.label} apps`}>
                  {apps.map((m) => (
                    <AppEntry key={m.app_key} manifest={m} location={location} />
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
