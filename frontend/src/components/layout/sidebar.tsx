import { Collapsible as CollapsiblePrimitive } from "radix-ui";
import { forwardRef, useState } from "react";
import { Link, useLocation, useSearch } from "wouter";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

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
    <CollapsiblePrimitive.Root open={expanded} onOpenChange={setExpanded} asChild>
      <li data-testid={`app-entry-${manifest.app_key}`}>
        <div
          className={cn(
            "flex items-center rounded-md transition-colors",
            isActive && "bg-[var(--accent-soft)]",
            isBlocked && "opacity-50",
          )}
          aria-disabled={isBlocked ? "true" : undefined}
          data-testid={`app-item-${manifest.app_key}`}
        >
          <Link
            href={appPath}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-3 py-1 text-[12.5px] text-[var(--ink-2)] no-underline transition-colors hover:text-[var(--ink-1)] hover:no-underline"
            aria-current={isActive ? "page" : undefined}
            data-testid="app-link"
          >
            <StatusShape kind={kind} size={STATUS_DOT_SIZE} />
            <span className="min-w-0 flex-1 truncate">{manifest.display_name}</span>
            {manifest.auto_loaded && (
              <Badge variant="muted" title="Auto-loaded">
                auto
              </Badge>
            )}
          </Link>
          {isMulti && (
            <CollapsiblePrimitive.Trigger asChild>
              <button
                type="button"
                className="mr-1 flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-sm border-none bg-transparent text-[var(--ink-3)] transition-colors hover:bg-[var(--bg-active)] hover:text-[var(--ink-1)] max-[900px]:size-11"
                aria-label={expanded ? `Collapse ${manifest.display_name}` : `Expand ${manifest.display_name}`}
                data-testid={`app-expand-${manifest.app_key}`}
              >
                <SidebarChevron open={expanded} />
              </button>
            </CollapsiblePrimitive.Trigger>
          )}
        </div>
        {isMulti && (
          <CollapsiblePrimitive.Content asChild>
            <ul className="flex list-none flex-col gap-px py-0 pr-0 pb-0 pl-4" data-testid="instance-list">
              {(manifest.instances ?? []).map((inst) => {
                const instHref = appDetailPath(manifest.app_key, undefined, { instance: inst.index });
                const pathMatches = location === appPath || location.startsWith(appPath + "/");
                const instanceParam = new URLSearchParams(searchString).get("instance");
                const instActive = pathMatches && instanceParam === String(inst.index);
                return (
                  <li key={inst.index} className="flex items-center gap-1">
                    <span className="shrink-0 font-mono text-xs text-[var(--ink-4)] select-none">└</span>
                    <Link
                      href={instHref}
                      className={cn(
                        "flex flex-1 items-center gap-2 rounded-sm px-2 py-0.5 text-xs text-[var(--ink-3)] no-underline transition-colors hover:text-[var(--ink-1)] hover:no-underline",
                        instActive && "font-medium text-[var(--accent)]",
                      )}
                      aria-current={instActive ? "page" : undefined}
                    >
                      <StatusShape kind={statusToKind(inst.status)} size={8} />
                      <span className="truncate">{inst.instance_name}</span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </CollapsiblePrimitive.Content>
        )}
      </li>
    </CollapsiblePrimitive.Root>
  );
}

interface StatusGroupHeaderProps extends React.ComponentPropsWithoutRef<"button"> {
  def: GroupDef;
  count: number;
  isOpen: boolean;
}

const StatusGroupHeader = forwardRef<HTMLButtonElement, StatusGroupHeaderProps>(function StatusGroupHeader(
  { def, count, isOpen, className, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={cn(
        "mx-2 flex w-[calc(100%-1rem)] cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-3 py-1 text-left font-inherit text-inherit select-none transition-colors hover:bg-[var(--bg-active)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--accent)]",
        className,
      )}
      data-testid="group-header"
      {...props}
    >
      <SidebarChevron open={isOpen} className="shrink-0 text-[var(--ink-4)]" />
      <StatusShape kind={def.tone} size={7} />
      <span
        className={cn(
          "flex-1 text-xs font-medium tracking-[0.05em] text-[var(--ink-2)] uppercase",
          def.tone === "err" && "text-[var(--err)]",
          def.tone === "warn" && "text-[var(--warn)]",
        )}
      >
        {def.label}
      </span>
      <span className="shrink-0 rounded-sm border border-[var(--line-1)] bg-[var(--bg-sunken)] px-1 font-mono text-xs leading-relaxed text-[var(--ink-4)]">
        {count}
      </span>
    </button>
  );
});

interface SidebarProps {
  onOpenPalette?: () => void;
  /** True when this instance renders inside the off-canvas mobile drawer rather than the desktop layout. */
  mobileDrawer?: boolean;
}

export function Sidebar({ onOpenPalette, mobileDrawer = false }: SidebarProps = {}) {
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
    <aside
      className={cn(
        "flex h-[calc(100vh-1rem)] w-60 shrink-0 flex-col overflow-hidden bg-transparent text-[var(--ink-2)]",
        "sticky top-2 z-[var(--z-sidebar)]",
        !mobileDrawer && "max-[900px]:hidden",
        mobileDrawer && "max-[900px]:top-0 max-[900px]:h-screen",
      )}
      data-testid="sidebar"
    >
      <div className="flex shrink-0 items-start justify-between gap-2 border-b border-[var(--line-2)] pt-4 pr-3 pb-2 pl-0">
        <div className="flex min-w-0 flex-col items-start">
          <Link
            href={HOME_PATH}
            className="flex items-center gap-2 px-4 no-underline hover:opacity-90 hover:no-underline"
            aria-label="Hassette home"
          >
            <span className="font-[family-name:var(--font-display)] text-base font-normal tracking-[-0.005em] text-[var(--ink-1)]">
              hassette
            </span>
          </Link>
          {version !== null && (
            <div className="flex flex-nowrap items-center gap-1 px-4 pb-2 font-mono text-xs text-[var(--ink-3)]">
              <span className="text-[var(--ink-3)]">v{version}</span>
            </div>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          className="max-[900px]:hidden"
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
        className="mx-3 my-2 flex cursor-pointer items-center justify-between rounded-md border border-[var(--line-1)] bg-[var(--bg-sunken)] px-3 py-2 text-xs text-[var(--ink-3)] transition-colors hover:border-[var(--line-strong)] hover:bg-[var(--bg-active)]"
        title={`Command palette (${SHORTCUT_HINT})`}
        aria-label="Open command palette"
        onClick={onOpenPalette}
      >
        <span>jump to…</span>
        <kbd className="font-mono text-xs text-[var(--ink-4)] max-[768px]:hidden">{SHORTCUT_HINT}</kbd>
      </button>

      <nav aria-label="Main navigation">
        <ul className="my-2 flex list-none flex-col gap-0.5 px-2">
          {NAV_PAGES.map((item) => {
            const isActive = location.startsWith(item.path);
            return (
              <li key={item.path}>
                <Link
                  href={item.path}
                  className={cn(
                    "flex items-center rounded-md px-3 py-2 text-sm text-[var(--ink-2)] no-underline transition-colors hover:bg-[var(--bg-active)] hover:text-[var(--ink-1)] hover:no-underline",
                    isActive && "bg-[var(--accent-soft)] font-medium text-[var(--accent)]",
                  )}
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

      <div className="flex-1 overflow-y-auto pt-1 pb-4" data-testid="app-nav">
        <div className="mt-1 flex items-center justify-between px-4 pt-2 pb-1">
          <span className="text-xs font-medium tracking-[0.07em] text-[var(--ink-2)] uppercase">APPS</span>
          <span className="font-mono text-xs text-[var(--ink-4)]">
            {isFiltering ? `${filteredCount}/${totalCount}` : totalCount}
          </span>
        </div>

        <div className="mt-1 border-t border-[var(--line-2)] px-3 py-2">
          <input
            type="search"
            className="w-full rounded-md border border-[var(--line-1)] bg-[var(--bg-sunken)] px-2 py-1 text-[12.5px] text-[var(--ink-1)] outline-none transition-colors placeholder:text-[var(--ink-4)] focus-visible:border-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--accent-soft)]"
            placeholder="Filter apps…"
            value={search}
            aria-label="Filter apps"
            data-testid="app-filter-input"
            onInput={(e) => setSearch((e.target as HTMLInputElement).value)}
          />
        </div>

        {manifestsLoading && <Spinner />}
        {!manifestsLoading && filtered.length === 0 && (
          <div className="block px-4 py-3 text-xs text-[var(--ink-4)]">no apps</div>
        )}
        {GROUP_DEFS.map((def) => {
          const apps = groups.get(def.key) ?? [];
          if (apps.length === 0) return null;
          const open = isGroupOpen(def.key);
          return (
            <CollapsiblePrimitive.Root key={def.key} open={open} onOpenChange={() => toggleGroup(def.key)} asChild>
              <div className="mb-0.5">
                <CollapsiblePrimitive.Trigger asChild>
                  <StatusGroupHeader def={def} count={apps.length} isOpen={open} />
                </CollapsiblePrimitive.Trigger>
                <CollapsiblePrimitive.Content asChild>
                  <ul className="flex list-none flex-col gap-px px-2" aria-label={`${def.label} apps`}>
                    {apps.map((m) => (
                      <AppEntry key={m.app_key} manifest={m} location={location} searchString={searchString} />
                    ))}
                  </ul>
                </CollapsiblePrimitive.Content>
              </div>
            </CollapsiblePrimitive.Root>
          );
        })}
      </div>

      {!chromeLivesInStatusBar && (
        <div
          className="flex shrink-0 items-center justify-between gap-3 border-t border-[var(--line-2)] px-4 py-3"
          data-testid="sidebar-footer"
        >
          <SystemHealth variant="stacked" />
          <ThemeToggle />
        </div>
      )}
    </aside>
  );
}
