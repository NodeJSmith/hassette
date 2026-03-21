import { useMemo } from "preact/hooks";
import { Route, Switch } from "wouter";
import { getManifests } from "./api/endpoints";
import { AlertBanner } from "./components/layout/alert-banner";
import { ErrorBoundary } from "./components/layout/error-boundary";
import { Sidebar } from "./components/layout/sidebar";
import { StatusBar } from "./components/layout/status-bar";
import { useApi } from "./hooks/use-api";
import { useWebSocket } from "./hooks/use-websocket";
import { AppDetailPage } from "./pages/app-detail";
import { AppsPage } from "./pages/apps";
import { DashboardPage } from "./pages/dashboard";
import { LogsPage } from "./pages/logs";
import { NotFoundPage } from "./pages/not-found";
import { AppStateContext } from "./state/context";
import { createAppState } from "./state/create-app-state";

export function App() {
  const state = useMemo(() => createAppState(), []);

  return (
    <AppStateContext.Provider value={state}>
      <WebSocketProvider state={state} />
      <div class="ht-layout">
        <Sidebar />
        <main class="ht-main">
          <StatusBar />
          <FailedAppsAlert />
          <ErrorBoundary>
            <Switch>
              <Route path="/" component={DashboardPage} />
              <Route path="/apps" component={AppsPage} />
              <Route path="/apps/:key/:index">{(params: { key: string; index: string }) => <AppDetailPage params={params} />}</Route>
              <Route path="/apps/:key">{(params: { key: string }) => <AppDetailPage params={params} />}</Route>
              <Route path="/logs" component={LogsPage} />
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

/** Renders the alert banner when apps have failed. */
function FailedAppsAlert() {
  const manifests = useApi(getManifests);
  const failedApps =
    manifests.data.value?.manifests
      .filter((m) => m.status === "failed")
      .map((m) => ({
        app_key: m.app_key,
        error_message: m.error_message,
      })) ?? [];

  return <AlertBanner failedApps={failedApps} />;
}
