import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Toaster } from "sonner";
import { Redirect, Route, Switch, useLocation, useSearch } from "wouter";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { cn } from "@/lib/utils";

import { type AppManifest, getAllListeners } from "./api/endpoints";
import { AlertBanner, TelemetryDegradedBanner } from "./components/layout/alert-banner";
import { ErrorBoundary } from "./components/layout/error-boundary";
import {
  buildActionItems,
  buildAppItems,
  buildHandlerItems,
  buildStaticPageItems,
  KIND_LABEL,
  KIND_ORDER,
  type PaletteItem,
  type PaletteItemKind,
} from "./components/layout/palette-items";
import { Sidebar } from "./components/layout/sidebar";
import { StatusBar } from "./components/layout/status-bar";
import { StatusShape } from "./components/shared/status-shape";
import { useManifests } from "./hooks/use-manifests";
import { BREAKPOINT_SIDEBAR, useMediaQuery } from "./hooks/use-media-query";
import { useTelemetryHealth } from "./hooks/use-telemetry-health";
import { useWebSocket } from "./hooks/use-websocket";
import { createQueryClient } from "./lib/query-client";
import { queryKeys } from "./lib/query-keys";
import { AppDetailPage } from "./pages/app-detail";
import { AppsPage } from "./pages/apps";
import { ConfigPage } from "./pages/config";
import { DesignPage } from "./pages/design";
import { DiagnosticsPage } from "./pages/diagnostics";
import { HandlersPage } from "./pages/handlers";
import { LoginPage } from "./pages/login";
import { LogsPage } from "./pages/logs";
import { NotFoundPage } from "./pages/not-found";
import { type AppStatusEntry, RELATIVE_TIME_TICK_MS, useAppStore } from "./state/store";
import { appLiveStatus } from "./utils/app-data";
import { HOME_PATH, LOGIN_PATH } from "./utils/app-routes";
import { isFailureStatus, statusToKind } from "./utils/status";

const PALETTE_STALE_TIME_MS = 300_000;
export const MAIN_CONTENT_ID = "main-content";
const SKIP_LINK_CLASS =
  "sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[var(--z-skip-link)] focus:rounded-md focus:border-2 focus:border-primary focus:bg-card focus:px-4 focus:py-2 focus:text-foreground";
const LAYOUT_CLASS =
  "relative grid min-h-screen min-h-dvh [grid-template-columns:var(--size-sidebar)_1fr] gap-2 pt-2 pr-2 pb-2 pl-0 max-sidebar:grid-cols-1 max-sidebar:gap-0 max-sidebar:p-0";
const MAIN_CLASS =
  "col-start-2 flex min-w-0 flex-col overflow-y-auto rounded-t-lg bg-card shadow-md [scrollbar-gutter:stable] max-sidebar:col-start-1 max-sidebar:rounded-none max-sidebar:shadow-none";

/** Where focus lands after the mobile drawer closes: the hamburger that opened it, or main content. */
type DrawerCloseFocusTarget = "main" | "opener";

/** Bare-key shortcuts must not fire while the user is typing into the app filter or palette. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;

  return (
    target.isContentEditable ||
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement
  );
}

export function App() {
  const queryClient = useMemo(() => createQueryClient(), []);
  const theme = useAppStore((s) => s.theme);
  const sidebarCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const [location] = useLocation();
  const search = useSearch();
  const belowSidebarBreakpoint = useMediaQuery(BREAKPOINT_SIDEBAR);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMounted, setDrawerMounted] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const hamburgerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const drawerEverOpenedRef = useRef(false);
  const prevDrawerOpenRef = useRef(drawerOpen);
  const drawerCloseFocusTargetRef = useRef<DrawerCloseFocusTarget>("opener");

  if (drawerOpen && !drawerMounted) setDrawerMounted(true);

  // Every close/toggle records where focus should land before flipping state, so the
  // focus-restoration effect below has exactly one place to read that decision from.
  const closeDrawer = useCallback((focusTarget: DrawerCloseFocusTarget = "opener") => {
    drawerCloseFocusTargetRef.current = focusTarget;
    setDrawerOpen(false);
  }, []);

  const toggleDrawer = useCallback(() => {
    drawerCloseFocusTargetRef.current = "opener";
    setDrawerOpen((prev) => !prev);
  }, []);

  useEffect(() => {
    const tickIfVisible = () => {
      if (!document.hidden) useAppStore.getState().incrementTick();
    };
    const id = setInterval(tickIfVisible, RELATIVE_TIME_TICK_MS);
    document.addEventListener("visibilitychange", tickIfVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tickIfVisible);
    };
  }, []);

  useEffect(() => {
    closeDrawer("main");
  }, [location, search, closeDrawer]);

  useEffect(() => {
    if (!belowSidebarBreakpoint) closeDrawer("main");
  }, [belowSidebarBreakpoint, closeDrawer]);

  useEffect(() => {
    if (drawerOpen) {
      drawerEverOpenedRef.current = true;
      const firstLink = drawerRef.current?.querySelector<HTMLElement>("a[href], button:not([disabled])");
      firstLink?.focus();
    } else if (drawerEverOpenedRef.current && prevDrawerOpenRef.current) {
      if (drawerCloseFocusTargetRef.current === "opener" && belowSidebarBreakpoint) {
        hamburgerRef.current?.focus();
      } else {
        document.getElementById(MAIN_CONTENT_ID)?.focus();
      }
      drawerCloseFocusTargetRef.current = "opener";
    }
    prevDrawerOpenRef.current = drawerOpen;
  }, [belowSidebarBreakpoint, drawerOpen]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
      if (e.key === "Escape" && drawerOpen) closeDrawer();
      // Collapsing is desktop-only: below the breakpoint the sidebar is a drawer and its
      // collapse toggle is hidden, so honoring [ there would silently flip persisted state
      // the user cannot see until they resize back.
      if (
        e.key === "[" &&
        !belowSidebarBreakpoint &&
        !e.metaKey &&
        !e.ctrlKey &&
        !e.altKey &&
        !isTypingTarget(e.target)
      ) {
        e.preventDefault();
        const next = !useAppStore.getState().sidebarCollapsed;
        useAppStore.getState().setSidebarCollapsed(next);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [drawerOpen, belowSidebarBreakpoint, closeDrawer]);

  // The login view bypasses the always-mounted shell entirely: WebSocketEffect and
  // TelemetryHealthEffect would immediately hit a rejected handshake / 401 against an
  // unauthenticated request, and the rejected-handshake redirect in use-websocket.ts would
  // send us right back here, looping. Sidebar/StatusBar also fetch data that would 401.
  if (location === LOGIN_PATH) {
    return (
      <QueryClientProvider client={queryClient}>
        <Toaster position="bottom-right" theme={theme} closeButton richColors />
        <LoginPage />
      </QueryClientProvider>
    );
  }

  return (
    <QueryClientProvider client={queryClient}>
      <>
        <WebSocketEffect />
        <TelemetryHealthEffect />
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        <Toaster position="bottom-right" theme={theme} closeButton richColors />

        {/* Skip link */}
        <a href={`#${MAIN_CONTENT_ID}`} className={SKIP_LINK_CLASS} data-testid="skip-link">
          Skip to main content
        </a>

        {/* Off-canvas drawer (mobile) */}
        <div
          ref={drawerRef}
          className={cn(
            "fixed top-0 bottom-0 left-0 z-[var(--z-drawer-layer)] w-[var(--size-sidebar)] overflow-y-auto bg-card transition-transform duration-[var(--duration-med)] ease-[var(--ease-default)]",
            drawerOpen ? "translate-x-0" : "-translate-x-full",
          )}
          aria-hidden={!drawerOpen}
          data-testid="mobile-drawer"
          inert={!drawerOpen}
        >
          {drawerMounted && (
            <>
              <div className="flex justify-end border-b border-border px-3 py-2">
                <button
                  type="button"
                  className="flex size-[var(--size-touch)] cursor-pointer items-center justify-center rounded-md border border-border bg-transparent text-foreground-secondary transition-colors hover:bg-[var(--highlight-bg)] hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary [&_svg]:size-5 [&_svg]:fill-none [&_svg]:stroke-current [&_svg]:stroke-2 [&_svg]:stroke-linecap-round [&_svg]:stroke-linejoin-round"
                  aria-label="Close navigation"
                  onClick={() => closeDrawer()}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <line x1="6" y1="6" x2="18" y2="18" />
                    <line x1="18" y1="6" x2="6" y2="18" />
                  </svg>
                </button>
              </div>
              <Sidebar mobileDrawer onOpenPalette={() => setPaletteOpen(true)} />
            </>
          )}
        </div>
        {drawerOpen && (
          <div
            className="fixed inset-0 z-[var(--z-drawer-backdrop)] bg-[var(--overlay-background)]"
            role="presentation"
            data-testid="mobile-drawer-backdrop"
            onClick={() => closeDrawer()}
          />
        )}

        {/* Desktop layout */}
        <div
          className={cn(
            LAYOUT_CLASS,
            sidebarCollapsed &&
              // `not-max-sidebar` is the exact complement of the `max-sidebar` (drawer) breakpoint
              // above, so both derive from `--breakpoint-sidebar` and can never drift apart.
              "is-collapsed not-max-sidebar:[grid-template-columns:0_1fr] not-max-sidebar:gap-0 not-max-sidebar:pl-2",
          )}
          data-testid="layout"
        >
          {!sidebarCollapsed && <Sidebar onOpenPalette={() => setPaletteOpen(true)} />}
          <main className={MAIN_CLASS} id={MAIN_CONTENT_ID} tabIndex={-1}>
            <StatusBar onMenuClick={toggleDrawer} drawerOpen={drawerOpen} hamburgerRef={hamburgerRef} />
            <div inert={drawerOpen}>
              <TelemetryDegradedBanner />
              <FailedAppsAlert />
              <ErrorBoundary resetKey={location}>
                <Switch>
                  <Route path="/">
                    <Redirect to={HOME_PATH} />
                  </Route>
                  {(["listener", "job"] as const).map((kind) => [
                    <Route key={`${kind}-exec`} path={`/apps/:key/handlers/${kind}/:id/exec/:execId`}>
                      {(params: { key: string; id: string; execId: string }) => (
                        <AppDetailPage
                          params={{
                            key: params.key,
                            tab: "handlers",
                            handler: `${kind}/${params.id}`,
                            execId: params.execId,
                          }}
                        />
                      )}
                    </Route>,
                    <Route key={kind} path={`/apps/:key/handlers/${kind}/:id`}>
                      {(params: { key: string; id: string }) => (
                        <AppDetailPage params={{ key: params.key, tab: "handlers", handler: `${kind}/${params.id}` }} />
                      )}
                    </Route>,
                  ])}
                  <Route path="/apps/:key/handlers">
                    {(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "handlers" }} />}
                  </Route>
                  <Route path="/apps/:key/code">
                    {(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "code" }} />}
                  </Route>
                  <Route path="/apps/:key/logs">
                    {(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "logs" }} />}
                  </Route>
                  <Route path="/apps/:key/config">
                    {(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "config" }} />}
                  </Route>
                  <Route path="/apps/:key/overview">
                    {(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "overview" }} />}
                  </Route>
                  <Route path="/apps/:key">
                    {(params: { key: string }) => <AppDetailPage params={{ key: params.key }} />}
                  </Route>
                  <Route path="/apps" component={AppsPage} />
                  <Route path="/handlers" component={HandlersPage} />
                  <Route path="/diagnostics" component={DiagnosticsPage} />
                  <Route path="/logs" component={LogsPage} />
                  <Route path="/config" component={ConfigPage} />
                  <Route path="/design" component={DesignPage} />
                  <Route component={NotFoundPage} />
                </Switch>
              </ErrorBoundary>
            </div>
          </main>
        </div>
      </>
    </QueryClientProvider>
  );
}

/** Side-effect component that wires up the WebSocket connection. */
function WebSocketEffect() {
  useWebSocket();
  return null;
}

/** Side-effect component that polls telemetry health status. */
function TelemetryHealthEffect() {
  useTelemetryHealth();
  return null;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

/** Cmd+K/Ctrl+K command palette: jump to pages, apps, handlers, or run quick actions. */
function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const [, navigate] = useLocation();
  const [query, setQuery] = useState("");

  // Start with a blank search each time the palette opens.
  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const { data: allManifests = [] } = useManifests();
  const appStatus = useAppStore((s) => s.appStatus);
  // Palette data changes infrequently and is only fetched when open — 5min staleTime
  // avoids refetching on every open while keeping results reasonably fresh.
  const { data: listeners } = useQuery({
    queryKey: queryKeys.allListenersPalette(),
    queryFn: ({ signal }) => getAllListeners(undefined, signal),
    enabled: open,
    staleTime: PALETTE_STALE_TIME_MS,
  });

  const pageItems = buildStaticPageItems(navigate);
  const actionItems = buildActionItems(allManifests, appStatus, onClose);
  const appItems = buildAppItems(allManifests, appStatus, navigate, onClose);
  const handlerItems = buildHandlerItems(listeners ?? [], navigate, onClose);

  const allItems: PaletteItem[] = [...pageItems, ...appItems, ...handlerItems, ...actionItems];

  // Groups are keyed by kind so cmdk's own fuzzy filter (matched against each item's
  // `value`) can hide/show items and their group heading as the user types.
  const sections: { kind: PaletteItemKind; items: PaletteItem[] }[] = KIND_ORDER.map((kind) => ({
    kind,
    items: allItems.filter((item) => item.kind === kind),
  })).filter((s) => s.items.length > 0);

  return (
    <CommandDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Command palette"
      description="Search apps, handlers, pages, actions"
    >
      <CommandInput
        placeholder="Search apps, handlers, pages, actions…"
        value={query}
        onValueChange={setQuery}
        data-testid="cmd-palette-input"
      />
      <CommandList data-testid="cmd-palette-results">
        <CommandEmpty data-testid="cmd-palette-empty">
          {query ? `No results for "${query}"` : "No items available"}
        </CommandEmpty>
        {sections.map((section) => (
          <CommandGroup
            key={section.kind}
            heading={KIND_LABEL[section.kind]}
            data-testid={`cmd-section-${section.kind}`}
          >
            {section.items.map((item) => (
              <CommandItem
                key={item.id}
                value={`${item.label} ${item.sub ?? ""} ${item.kind}`}
                data-testid={`cmd-result-${item.id}`}
                onSelect={() => item.action()}
              >
                {item.status !== undefined && <StatusShape kind={statusToKind(item.status)} size={8} />}
                <span>{item.label}</span>
                {item.sub && <span className="ml-1 text-xs text-muted-foreground">{item.sub}</span>}
                <span className="ml-auto text-xs text-muted-foreground">{item.kind}</span>
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
      <div
        className="flex items-center gap-4 border-t px-3 py-2 text-xs text-muted-foreground"
        data-testid="cmd-palette-footer"
      >
        <span>
          <kbd>↑↓</kbd> navigate
        </span>
        <span>
          <kbd>↵</kbd> select
        </span>
        <span>
          <kbd>esc</kbd> close
        </span>
      </div>
    </CommandDialog>
  );
}

interface FailedApp {
  app_key: string;
  error_message: string | null;
}

/** Single source of truth for "which manifests are currently failed" — shared by the zustand
 * selector and the `useMemo` below so the two can never drift out of lockstep with each other
 * (a field added to `FailedApp` only has to be added here, not mirrored into a second hand-joined
 * key string). */
function computeFailedApps(manifests: AppManifest[], appStatuses: Record<string, AppStatusEntry>): FailedApp[] {
  return manifests
    .filter((m) => isFailureStatus(appLiveStatus(appStatuses, m)))
    .map((m) => ({
      app_key: m.app_key,
      error_message: m.error_message ?? null,
    }));
}

/**
 * Renders the alert banner when apps have failed.
 *
 * This component is mounted unconditionally above the routed `<Switch>` (see `App()`), so it's
 * live on every page. `updateAppStatus` in `state/store.ts` spreads the ENTIRE `appStatus` record
 * into a brand-new object on every single `app_status_changed` WS message, for any app/instance —
 * so a naive `useAppStore((s) => s.appStatus)` selector would return a new reference (and force a
 * re-render + full manifest re-scan) on every unrelated status write anywhere in the system.
 *
 * The zustand selector below returns a stable, sorted primitive string instead — the same
 * "selector must return a primitive" invariant `app-detail.tsx`'s `liveStatus` selector relies on
 * for referential equality to actually hold (a freshly-built object or array compares unequal on
 * every store write no matter its contents, which is also why zustand's `useShallow` doesn't help
 * here: its one-level shallow-equal check still sees fresh `{app_key, error_message}` objects as
 * different on every recompute). Zustand still re-invokes the selector on every `appStatus` write
 * — the filter+map+join is cheap — but only triggers a re-render when the resulting string
 * differs, i.e. when the actual set of failing apps (or their messages) changes.
 *
 * The real `{app_key, error_message}[]` array `AlertBanner` needs is then derived via `useMemo`
 * keyed on that string (plus `manifests`, since `error_message` and the manifest list itself can
 * change independent of `appStatus`), reading a one-time snapshot of `appStatus` via `getState()`
 * rather than subscribing to it a second time. Both the key and the array are built from
 * `computeFailedApps()` so there's only one place that decides which fields identify a "failed
 * app" — see its doc comment.
 */
function FailedAppsAlert() {
  const { data: manifests = [] } = useManifests();

  const failedAppsKey = useAppStore((s) =>
    computeFailedApps(manifests, s.appStatus)
      .map((f) => `${f.app_key}:${f.error_message ?? ""}`)
      .join("|"),
  );

  const failedApps = useMemo(() => {
    const appStatuses = useAppStore.getState().appStatus;
    return computeFailedApps(manifests, appStatuses);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- appStatus is read via getState(), not subscribed; failedAppsKey drives recomputation
  }, [failedAppsKey, manifests]);

  return <AlertBanner failedApps={failedApps} />;
}
