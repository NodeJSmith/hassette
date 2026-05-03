import { useEffect, useMemo, useState } from "preact/hooks";
import { Route, Switch, useLocation } from "wouter";
import { getManifests } from "./api/endpoints";
import { AlertBanner } from "./components/layout/alert-banner";
import { CommandPalette } from "./components/layout/command-palette";
import { ErrorBoundary } from "./components/layout/error-boundary";
import { Sidebar } from "./components/layout/sidebar";
import { StatusBar } from "./components/layout/status-bar";
import { useApi } from "./hooks/use-api";
import { useTelemetryHealth } from "./hooks/use-telemetry-health";
import { useWebSocket } from "./hooks/use-websocket";
import { AppDetailPage } from "./pages/app-detail";
import { AppsPage } from "./pages/apps";
import { ConfigPage } from "./pages/config";
import { DashboardPage } from "./pages/dashboard";
import { LogsPage } from "./pages/logs";
import { NotFoundPage } from "./pages/not-found";
import { AppStateContext } from "./state/context";
import { createAppState } from "./state/create-app-state";

export function App() {
  const state = useMemo(() => createAppState(), []);
  const [location] = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMounted, setDrawerMounted] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  if (drawerOpen && !drawerMounted) setDrawerMounted(true);

  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) state.tick.value++; }, 30_000);
    return () => clearInterval(id);
  }, [state]);

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
    <AppStateContext.Provider value={state}>
      <WebSocketProvider state={state} />
      <TelemetryHealthProvider state={state} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />

      {/* Skip link */}
      <a href="#main-content" class="ht-skip-link">Skip to main content</a>

      {/* Hamburger button (mobile) */}
      <button
        type="button"
        class="ht-hamburger"
        aria-label="Open navigation"
        aria-expanded={drawerOpen}
        onClick={() => setDrawerOpen(true)}
      >
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      </button>

      {/* Off-canvas drawer (mobile) */}
      <div
        class={`ht-drawer${drawerOpen ? " is-open" : ""}`}
        aria-hidden={!drawerOpen}
      >
        {drawerMounted && <Sidebar onOpenPalette={() => setPaletteOpen(true)} />}
      </div>
      {drawerOpen && (
        <div
          class="ht-drawer-backdrop"
          role="presentation"
          onClick={() => setDrawerOpen(false)}
        />
      )}

      {/* Desktop layout */}
      <div class="ht-layout">
        <Sidebar onOpenPalette={() => setPaletteOpen(true)} />
        <main class="ht-main" id="main-content" tabIndex={-1}>
          <StatusBar />
          <FailedAppsAlert />
          <ErrorBoundary resetKey={location}>
            <Switch>
              <Route path="/" component={DashboardPage} />
              <Route path="/apps" component={AppsPage} />
              <Route path="/apps/:key/:index">{(params: { key: string; index: string }) => <AppDetailPage params={params} />}</Route>
              <Route path="/apps/:key">{(params: { key: string }) => <AppDetailPage params={params} />}</Route>
              <Route path="/logs" component={LogsPage} />
              <Route path="/config" component={ConfigPage} />
              <Route component={NotFoundPage} />
            </Switch>
          </ErrorBoundary>
        </main>
      </div>
    </AppStateContext.Provider>
  );
}

/** Invisible component that wires up the WebSocket connection. */
function WebSocketProvider({ state }: { state: ReturnType<typeof createAppState> }) {
  useWebSocket(state);
  return null;
}

/** Invisible component that polls telemetry health status. */
function TelemetryHealthProvider({ state }: { state: ReturnType<typeof createAppState> }) {
  useTelemetryHealth(state);
  return null;
}

/** Renders the alert banner when apps have failed. */
function FailedAppsAlert() {
  const manifests = useApi(getManifests);
  const failedApps =
    manifests.data.value?.manifests
      .filter((m) => m.status === "failed")
      .map((m) => ({
        app_key: m.app_key,
        error_message: m.error_message ?? null,
      })) ?? [];

  return <AlertBanner failedApps={failedApps} />;
}
