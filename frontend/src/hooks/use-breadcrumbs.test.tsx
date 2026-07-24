import { signal } from "@preact/signals";
import { QueryClient, QueryClientProvider } from "@tanstack/preact-query";
import { render, waitFor } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { AppStateContext } from "../state/context";
import { createAppState } from "../state/create-app-state";
import { server } from "../test/server";
import { useBreadcrumbs } from "./use-breadcrumbs";

const location = signal("/apps/demo_app/handlers/job/7");

// Repo convention: mock wouter's hooks rather than mounting a real Router.
vi.mock("wouter", () => ({
  useLocation: () => [location.value],
  useSearch: () => "",
}));

function Probe() {
  const crumbs = useBreadcrumbs();

  return <span data-testid="trail">{crumbs.map((c) => c.label).join(" / ")}</span>;
}

function renderProbe() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // effectiveTimePreset is a computed over the original timePreset signal, so it has to be
  // overridden directly to pin the time window this test's query key resolves to.
  const state = { ...createAppState(), effectiveTimePreset: signal("1h") };

  return render(
    <QueryClientProvider client={queryClient}>
      <AppStateContext.Provider value={state as never}>
        <Probe />
      </AppStateContext.Provider>
    </QueryClientProvider>,
  );
}

describe("useBreadcrumbs", () => {
  it("falls back to the handler id while the fetch is in flight", () => {
    const { getByTestId } = renderProbe();
    expect(getByTestId("trail").textContent).toBe("apps / demo_app / handlers / job 7");
  });

  it("upgrades the job crumb to its name once the query lands", async () => {
    // Regression: the trail used to read the cache non-reactively (getQueryData, then a
    // skipToken observer). Neither re-renders on a cache write, so the crumb stayed on
    // its "job 7" fallback until something unrelated happened to re-render the status bar.
    server.use(
      http.get("/api/telemetry/app/:app_key/jobs", () =>
        HttpResponse.json([{ job_id: 7, job_name: "sensor_health_check" }]),
      ),
    );
    const { getByTestId } = renderProbe();
    expect(getByTestId("trail").textContent).toContain("job 7");

    await waitFor(() =>
      expect(getByTestId("trail").textContent).toBe("apps / demo_app / handlers / sensor_health_check"),
    );
  });

  it("upgrades the listener crumb to its handler method's last segment", async () => {
    location.value = "/apps/demo_app/handlers/listener/42";
    server.use(
      http.get("/api/telemetry/app/:app_key/listeners", () =>
        HttpResponse.json([{ listener_id: 42, handler_method: "myapp.MyApp.on_kitchen_light" }]),
      ),
    );
    const { getByTestId } = renderProbe();

    await waitFor(() => expect(getByTestId("trail").textContent).toBe("apps / demo_app / handlers / on_kitchen_light"));
    location.value = "/apps/demo_app/handlers/job/7";
  });

  it("does not query on routes with no handler crumb", async () => {
    location.value = "/apps/demo_app";
    let listenerCalls = 0;
    server.use(
      http.get("/api/telemetry/app/:app_key/listeners", () => {
        listenerCalls++;
        return HttpResponse.json([]);
      }),
    );
    const { getByTestId } = renderProbe();

    expect(getByTestId("trail").textContent).toBe("apps / demo_app");
    await new Promise((r) => setTimeout(r, 50));
    expect(listenerCalls).toBe(0);
    location.value = "/apps/demo_app/handlers/job/7";
  });
});
