import { QueryClientProvider } from "@tanstack/preact-query";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Toaster } from "sonner";
import { Redirect, Route, Switch, useLocation } from "wouter";

import { AlertBanner, TelemetryDegradedBanner } from "./components/layout/alert-banner";
import { CommandPalette } from "./components/layout/command-palette";
import { ErrorBoundary } from "./components/layout/error-boundary";
import { Sidebar } from "./components/layout/sidebar";
import { StatusBar } from "./components/layout/status-bar";
import { useManifests } from "./hooks/use-manifests";
import { useTelemetryHealth } from "./hooks/use-telemetry-health";
import { useWebSocket } from "./hooks/use-websocket";
import { createQueryClient } from "./lib/query-client";
import { AppDetailPage } from "./pages/app-detail";
import { AppsPage } from "./pages/apps";
import { ConfigPage } from "./pages/config";
import { DesignPage } from "./pages/design";
import { DiagnosticsPage } from "./pages/diagnostics";
import { HandlersPage } from "./pages/handlers";
import { LogsPage } from "./pages/logs";
import { NotFoundPage } from "./pages/not-found";
import { AppStateContext } from "./state/context";
import { createAppState, RELATIVE_TIME_TICK_MS } from "./state/create-app-state";

export function App() {
  const queryClient = useMemo(() => createQueryClient(), []);
  const state = useMemo(() => createAppState(), []);
  const [location] = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMounted, setDrawerMounted] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const hamburgerRef = useRef<HTMLButtonElement>(null);
  const drawerRef = useRef<HTMLDivElement>(null);
  const drawerEverOpenedRef = useRef(false);

  if (drawerOpen && !drawerMounted) setDrawerMounted(true);

  useEffect(() => {
    const id = setInterval(() => {
      if (!document.hidden) state.tick.value++;
    }, RELATIVE_TIME_TICK_MS);
    const onVisible = () => {
      if (!document.hidden) state.tick.value++;
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [state]);

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
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [drawerOpen]);

  return (
    <QueryClientProvider client={queryClient}>
      <AppStateContext.Provider value={state}>
        <WebSocketEffect state={state} />
        <TelemetryHealthEffect state={state} />
        <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
        <Toaster position="bottom-right" theme={state.theme.value} closeButton richColors />

        {/* Skip link */}
        <a href="#main-content" class="ht-skip-link">
          Skip to main content
        </a>

        {/* Off-canvas drawer (mobile) */}
        <div ref={drawerRef} class={`ht-drawer${drawerOpen ? " is-open" : ""}`} aria-hidden={!drawerOpen}>
          {drawerMounted && <Sidebar onOpenPalette={() => setPaletteOpen(true)} />}
        </div>
        {drawerOpen && <div class="ht-drawer-backdrop" role="presentation" onClick={() => setDrawerOpen(false)} />}

        {/* Desktop layout */}
        <div class="ht-layout" data-testid="layout">
          <Sidebar onOpenPalette={() => setPaletteOpen(true)} />
          <main class="ht-main" id="main-content" tabIndex={-1}>
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
                    <Redirect to="/apps" />
                  </Route>
                  <Route path="/apps/:key/handlers/listener/:id">
                    {(params: { key: string; id: string }) => (
                      <AppDetailPage params={{ key: params.key, tab: "handlers", handler: `listener/${params.id}` }} />
                    )}
                  </Route>
                  <Route path="/apps/:key/handlers/job/:id">
                    {(params: { key: string; id: string }) => (
                      <AppDetailPage params={{ key: params.key, tab: "handlers", handler: `job/${params.id}` }} />
                    )}
                  </Route>
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
      </AppStateContext.Provider>
    </QueryClientProvider>
  );
}

/** Side-effect component that wires up the WebSocket connection. */
function WebSocketEffect({ state }: { state: ReturnType<typeof createAppState> }) {
  useWebSocket(state);
  return null;
}

/** Side-effect component that polls telemetry health status. */
function TelemetryHealthEffect({ state }: { state: ReturnType<typeof createAppState> }) {
  useTelemetryHealth(state);
  return null;
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
