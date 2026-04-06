import { useEffect, useMemo } from "preact/hooks";
import { Route, Switch, useLocation } from "wouter";
import { getManifests } from "./api/endpoints";
import { AlertBanner } from "./components/layout/alert-banner";
import { ErrorBoundary } from "./components/layout/error-boundary";
import { BottomNav } from "./components/layout/bottom-nav";
import { Sidebar } from "./components/layout/sidebar";
import { StatusBar } from "./components/layout/status-bar";
import { useApi } from "./hooks/use-api";
import { useTelemetryHealth } from "./hooks/use-telemetry-health";
import { useWebSocket } from "./hooks/use-websocket";
import { AppDetailPage } from "./pages/app-detail";
import { AppsPage } from "./pages/apps";
import { DashboardPage } from "./pages/dashboard";
import { LogsPage } from "./pages/logs";
import { NotFoundPage } from "./pages/not-found";
import { SessionsPage } from "./pages/sessions";
import { AppStateContext } from "./state/context";
import { createAppState } from "./state/create-app-state";

export function App() {
  const state = useMemo(() => createAppState(), []);
  const [location] = useLocation();

  useEffect(() => {
    const id = setInterval(() => { if (!document.hidden) state.tick.value++; }, 30_000);
    return () => clearInterval(id);
  }, [state]);

  return (
    <AppStateContext.Provider value={state}>
      <WebSocketProvider state={state} />
      <TelemetryHealthProvider state={state} />
      <div class="ht-layout">
        <a href="#main-content" class="ht-skip-link">Skip to main content</a>
        <Sidebar />
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
              <Route path="/sessions" component={SessionsPage} />
              <Route component={NotFoundPage} />
            </Switch>
          </ErrorBoundary>
        </main>
      </div>
      <BottomNav />
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
