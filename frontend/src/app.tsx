import { useMemo } from "preact/hooks";
import { Route, Switch } from "wouter";
import { ErrorBoundary } from "./components/layout/error-boundary";
import { Sidebar } from "./components/layout/sidebar";
import { StatusBar } from "./components/layout/status-bar";
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
          <ErrorBoundary>
            <Switch>
              <Route path="/" component={DashboardPage} />
              <Route path="/apps" component={AppsPage} />
              <Route path="/apps/:key">{(params) => <AppDetailPage params={params} />}</Route>
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
