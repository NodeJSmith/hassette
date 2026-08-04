import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
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

import { getAllListeners } from "./api/endpoints";
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
import { RELATIVE_TIME_TICK_MS, useAppStore } from "./state/store";
import { HOME_PATH, LOGIN_PATH } from "./utils/app-routes";
import { statusToKind } from "./utils/status";

const PALETTE_STALE_TIME_MS = 300_000;
const SKIP_LINK_CLASS =
  "sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[var(--z-skip-link)] focus:rounded-md focus:border-2 focus:border-primary focus:bg-card focus:px-4 focus:py-2 focus:text-foreground";
const LAYOUT_CLASS =
  "relative grid min-h-screen min-h-dvh [grid-template-columns:var(--size-sidebar)_1fr] gap-2 pt-2 pr-2 pb-2 pl-0 max-sidebar:grid-cols-1 max-sidebar:gap-0 max-sidebar:p-0";
const MAIN_CLASS =
  "col-start-2 flex min-w-0 flex-col overflow-y-auto rounded-t-lg bg-card shadow-md [scrollbar-gutter:stable] max-sidebar:col-start-1 max-sidebar:rounded-none max-sidebar:shadow-none";

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
  const drawerCloseFocusTargetRef = useRef<"main" | "opener">("opener");

  if (drawerOpen && !drawerMounted) setDrawerMounted(true);

  useEffect(() => {
    const id = setInterval(() => {
      if (!document.hidden) useAppStore.getState().incrementTick();
    }, RELATIVE_TIME_TICK_MS);
    const onVisible = () => {
      if (!document.hidden) useAppStore.getState().incrementTick();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  useEffect(() => {
    drawerCloseFocusTargetRef.current = "main";
    setDrawerOpen(false);
  }, [location, search]);

  useEffect(() => {
    if (!belowSidebarBreakpoint) {
      drawerCloseFocusTargetRef.current = "main";
      setDrawerOpen(false);
    }
  }, [belowSidebarBreakpoint]);

  useEffect(() => {
    if (drawerOpen) {
      drawerEverOpenedRef.current = true;
      const firstLink = drawerRef.current?.querySelector<HTMLElement>("a[href], button:not([disabled])");
      firstLink?.focus();
    } else if (drawerEverOpenedRef.current && prevDrawerOpenRef.current) {
      if (drawerCloseFocusTargetRef.current === "opener" && belowSidebarBreakpoint) {
        hamburgerRef.current?.focus();
      } else {
        document.getElementById("main-content")?.focus();
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
      if (e.key === "Escape" && drawerOpen) {
        drawerCloseFocusTargetRef.current = "opener";
        setDrawerOpen(false);
      }
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
  }, [drawerOpen, belowSidebarBreakpoint]);

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
        <a href="#main-content" className={SKIP_LINK_CLASS} data-testid="skip-link">
          Skip to main content
        </a>

        {/* Off-canvas drawer (mobile) */}
        <div
          ref={drawerRef}
          className={cn(
            "fixed top-0 bottom-0 left-0 z-[var(--z-drawer-layer)] w-60 overflow-y-auto bg-card transition-transform duration-[var(--duration-med)] ease-[var(--ease-default)]",
            drawerOpen ? "translate-x-0" : "-translate-x-full",
          )}
          aria-hidden={!drawerOpen}
          data-testid="mobile-drawer"
          {...(!drawerOpen ? { inert: true } : {})}
        >
          {drawerMounted && (
            <>
              <div className="flex justify-end border-b border-border px-3 py-2">
                <button
                  type="button"
                  className="flex size-[var(--size-touch)] cursor-pointer items-center justify-center rounded-md border border-border bg-transparent text-foreground-secondary transition-colors hover:bg-[var(--highlight-bg)] hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary [&_svg]:size-5 [&_svg]:fill-none [&_svg]:stroke-current [&_svg]:stroke-2 [&_svg]:stroke-linecap-round [&_svg]:stroke-linejoin-round"
                  aria-label="Close navigation"
                  onClick={() => {
                    drawerCloseFocusTargetRef.current = "opener";
                    setDrawerOpen(false);
                  }}
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
            onClick={() => {
              drawerCloseFocusTargetRef.current = "opener";
              setDrawerOpen(false);
            }}
          />
        )}

        {/* Desktop layout */}
        <div
          className={cn(
            LAYOUT_CLASS,
            sidebarCollapsed &&
              "is-collapsed min-[901px]:[grid-template-columns:0_1fr] min-[901px]:gap-0 min-[901px]:pl-2",
          )}
          data-testid="layout"
        >
          {!sidebarCollapsed && <Sidebar onOpenPalette={() => setPaletteOpen(true)} />}
          <main className={MAIN_CLASS} id="main-content" tabIndex={-1}>
            <StatusBar
              onMenuClick={() => {
                drawerCloseFocusTargetRef.current = "opener";
                setDrawerOpen((prev) => !prev);
              }}
              drawerOpen={drawerOpen}
              hamburgerRef={hamburgerRef}
            />
            <div {...(drawerOpen ? { inert: true } : {})}>
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
  // Palette data changes infrequently and is only fetched when open — 5min staleTime
  // avoids refetching on every open while keeping results reasonably fresh.
  const { data: listeners } = useQuery({
    queryKey: queryKeys.allListenersPalette(),
    queryFn: ({ signal }) => getAllListeners(undefined, signal),
    enabled: open,
    staleTime: PALETTE_STALE_TIME_MS,
  });

  const pageItems = buildStaticPageItems(navigate);
  const actionItems = buildActionItems(allManifests, onClose);
  const appItems = buildAppItems(allManifests, navigate, onClose);
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

/** Renders the alert banner when apps have failed. */
function FailedAppsAlert() {
  const { data: manifests = [] } = useManifests();
  const failedApps = manifests
    .filter((m) => m.status === "failed")
    .map((m) => ({
      app_key: m.app_key,
      error_message: m.error_message ?? null,
    }));

  return <AlertBanner failedApps={failedApps} />;
}
