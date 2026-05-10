import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Redirect, Route, Switch, useLocation } from "wouter";
import { AlertBanner, TelemetryDegradedBanner } from "./components/layout/alert-banner";
import { CommandPalette } from "./components/layout/command-palette";
import { ErrorBoundary } from "./components/layout/error-boundary";
import { Sidebar } from "./components/layout/sidebar";
import { StatusBar } from "./components/layout/status-bar";
import { useManifestFetcher } from "./hooks/use-manifest-fetcher";
import { useTelemetryHealth } from "./hooks/use-telemetry-health";
import { useWebSocket } from "./hooks/use-websocket";
import { AppDetailPage } from "./pages/app-detail";
import { AppsPage } from "./pages/apps";
import { ConfigPage } from "./pages/config";
import { DiagnosticsPage } from "./pages/diagnostics";
import { HandlersPage } from "./pages/handlers";
import { LogsPage } from "./pages/logs";
import { NotFoundPage } from "./pages/not-found";
import { AppStateContext, useAppState } from "./state/context";
import { createAppState, RELATIVE_TIME_TICK_MS } from "./state/create-app-state";

export function App() {
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
    const id = setInterval(() => { if (!document.hidden) state.tick.value++; }, RELATIVE_TIME_TICK_MS);
    return () => clearInterval(id);
  }, [state]);

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
    <AppStateContext.Provider value={state}>
      <WebSocketProvider state={state} />
      <ManifestProvider state={state} />
      <TelemetryHealthProvider state={state} />
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />

      {/* Skip link */}
      <a href="#main-content" class="ht-skip-link">Skip to main content</a>

      {/* Hamburger button (mobile) */}
      <button
        ref={hamburgerRef}
        type="button"
        class="ht-hamburger"
        aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
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
        ref={drawerRef}
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
      <div class="ht-layout" {...(drawerOpen ? { inert: true } : {})}>

        <Sidebar onOpenPalette={() => setPaletteOpen(true)} />
        <main class="ht-main" id="main-content" tabIndex={-1}>
          <StatusBar />
          <TelemetryDegradedBanner />
          <FailedAppsAlert />
          <ErrorBoundary resetKey={location}>
            <Switch>
              <Route path="/"><Redirect to="/apps" /></Route>
              <Route path="/apps/:key/handlers/:handlerId">{(params: { key: string; handlerId: string }) => <AppDetailPage params={{ key: params.key, tab: "handlers", handler: params.handlerId }} />}</Route>
              <Route path="/apps/:key/handlers">{(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "handlers" }} />}</Route>
              <Route path="/apps/:key/code">{(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "code" }} />}</Route>
              <Route path="/apps/:key/logs">{(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "logs" }} />}</Route>
              <Route path="/apps/:key/config">{(params: { key: string }) => <AppDetailPage params={{ key: params.key, tab: "config" }} />}</Route>
              <Route path="/apps/:key">{(params: { key: string }) => <AppDetailPage params={{ key: params.key }} />}</Route>
              <Route path="/apps" component={AppsPage} />
              <Route path="/handlers" component={HandlersPage} />
              <Route path="/diagnostics" component={DiagnosticsPage} />
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
  const { manifests } = useAppState();
  const failedApps = manifests.value
    .filter((m) => m.status === "failed")
    .map((m) => ({
      app_key: m.app_key,
      error_message: m.error_message ?? null,
    }));

  return <AlertBanner failedApps={failedApps} />;
}

/** Invisible component that fetches manifests once and refetches on reconnect. */
function ManifestProvider({ state }: { state: ReturnType<typeof createAppState> }) {
  useManifestFetcher(state);
  return null;
}
