import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Toaster } from "sonner";
import { Redirect, Route, Switch, useLocation } from "wouter";

import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";

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
import { LogsPage } from "./pages/logs";
import { NotFoundPage } from "./pages/not-found";
import { RELATIVE_TIME_TICK_MS, useAppStore } from "./state/store";
import { HOME_PATH } from "./utils/app-routes";
import { statusToKind } from "./utils/status";

const PALETTE_STALE_TIME_MS = 300_000;

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
  const belowSidebarBreakpoint = useMediaQuery(BREAKPOINT_SIDEBAR);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMounted, setDrawerMounted] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const hamburgerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const drawerEverOpenedRef = useRef(false);

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

  const pathname = location.split("?")[0];

  useEffect(() => {
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (drawerOpen) {
      drawerEverOpenedRef.current = true;
      const firstLink = drawerRef.current?.querySelector<HTMLElement>("a[href], button:not([disabled])");
      firstLink?.focus();
    } else if (drawerEverOpenedRef.current) {
      hamburgerRef.current?.focus();
    }
  }, [drawerOpen]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
      }
      if (e.key === "Escape" && drawerOpen) {
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

  return (
    <QueryClientProvider client={queryClient}>
      <>
        <WebSocketEffect />
        <TelemetryHealthEffect />
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        <Toaster position="bottom-right" theme={theme} closeButton richColors />

        {/* Skip link */}
        <a href="#main-content" className="ht-skip-link">
          Skip to main content
        </a>

        {/* Off-canvas drawer (mobile) */}
        <div
          ref={drawerRef}
          className={`ht-drawer${drawerOpen ? " is-open" : ""}`}
          aria-hidden={!drawerOpen}
          {...(!drawerOpen ? { inert: true } : {})}
        >
          {drawerMounted && <Sidebar onOpenPalette={() => setPaletteOpen(true)} />}
        </div>
        {drawerOpen && <div className="ht-drawer-backdrop" role="presentation" onClick={() => setDrawerOpen(false)} />}

        {/* Desktop layout */}
        <div className={`ht-layout${sidebarCollapsed ? " is-collapsed" : ""}`} data-testid="layout">
          {!sidebarCollapsed && <Sidebar onOpenPalette={() => setPaletteOpen(true)} />}
          <main className="ht-main" id="main-content" tabIndex={-1}>
            <StatusBar
              onMenuClick={() => setDrawerOpen((prev) => !prev)}
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
