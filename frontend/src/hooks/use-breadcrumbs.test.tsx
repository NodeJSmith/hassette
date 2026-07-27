import { waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createWouterMock } from "../test/mock-wouter";
import { renderWithAppState } from "../test/render-helpers";
import { server } from "../test/server";
import { useBreadcrumbs } from "./use-breadcrumbs";

const DEFAULT_LOCATION = "/apps/demo_app/handlers/job/7";
// Module-level mutable location for the wouter mock — plain object, not a signal.
const location = { value: DEFAULT_LOCATION };

// Repo convention: mock wouter's hooks rather than mounting a real Router.
vi.mock("wouter", () =>
  createWouterMock({
    useLocation: () => [location.value],
    useSearch: () => "",
  }),
);

function Probe() {
  const crumbs = useBreadcrumbs();

  return <span data-testid="trail">{crumbs.map((c) => c.label).join(" / ")}</span>;
}

function renderProbe() {
  // effectiveTimePreset is derived as `urlWindowParam ?? timePreset` — set urlWindowParam
  // directly to pin the time window this test's query key resolves to.
  return renderWithAppState(<Probe />, { storeOverrides: { urlWindowParam: "1h" } });
}

describe("useBreadcrumbs", () => {
  // `location` is module-level shared state. Resetting it here rather than at the end of
  // each test body means a test that throws mid-way cannot leak its route into the next
  // one and turn one failure into a confusing cascade.
  afterEach(() => {
    location.value = DEFAULT_LOCATION;
  });

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
  });
});
