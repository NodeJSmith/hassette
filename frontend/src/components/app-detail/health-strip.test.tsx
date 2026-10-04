import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AppHealthData } from "../../api/endpoints";
import { WS_DEBOUNCE_MAX_WAIT_MS } from "../../hooks/use-query-invalidator";
import { useAppStore } from "../../state/store";
import { createAppHealth, createExecutionCompletedPayload } from "../../test/factories";
import { mockMediaQueryMatches, renderWithAppState } from "../../test/render-helpers";
import { server } from "../../test/server";
import { OverviewHealthStrip } from "./health-strip";

const CELL_SELECTOR = "[data-testid='stats-strip-cell']";
const ERR_TONE_SELECTOR = "[data-tone='err']";
const STRIP_TESTID = "overview-health-strip";
const HEALTH_ROUTE = "/api/telemetry/app/:app_key/health";

const COL_HANDLERS = 0;
const COL_ERROR_RATE = 1;
const COL_HANDLER_AVG = 2;
const COL_JOB_AVG = 3;

function serveHealth(health: AppHealthData) {
  const requests: URL[] = [];
  server.use(
    http.get(HEALTH_ROUTE, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(health);
    }),
  );
  return requests;
}

function renderStrip({ handlerCount = 3, resolvedInstanceIndex = 0 } = {}) {
  const result = renderWithAppState(
    <OverviewHealthStrip appKey="my_app" resolvedInstanceIndex={resolvedInstanceIndex} handlerCount={handlerCount} />,
    // useScopedQuery holds since-restart queries until uptime is known.
    { storeOverrides: { uptimeSeconds: 120 } },
  );
  const cards = () => result.container.querySelectorAll(CELL_SELECTOR);
  return { ...result, cards };
}

describe("OverviewHealthStrip", () => {
  afterEach(() => vi.restoreAllMocks());

  it("renders the handler count and the server's health for the instance", async () => {
    const requests = serveHealth(
      createAppHealth({ error_rate: 8.4, handler_avg_duration_ms: 120, job_avg_duration_ms: 2500 }),
    );
    const { cards } = renderStrip({ handlerCount: 7, resolvedInstanceIndex: 2 });

    await waitFor(() => expect(cards()[COL_ERROR_RATE].textContent).toContain("8%"));
    expect(cards()[COL_HANDLERS].textContent).toContain("7");
    expect(cards()[COL_HANDLER_AVG].textContent).toContain("120");
    expect(cards()[COL_JOB_AVG].textContent).toContain("2.5s");
    expect(requests[0].searchParams.get("instance_index")).toBe("2");
  });

  it("applies the err tone to ERROR RATE only when the server reports errors", async () => {
    serveHealth(createAppHealth({ error_rate: 2 }));
    const { cards } = renderStrip();
    await waitFor(() => expect(cards()[COL_ERROR_RATE].textContent).toContain("2%"));
    expect(cards()[COL_ERROR_RATE].querySelector(ERR_TONE_SELECTOR)).not.toBeNull();
  });

  it("shows a positive error rate below 1% as <1% with the err tone", async () => {
    serveHealth(createAppHealth({ error_rate: 0.3 }));
    const { cards } = renderStrip();
    await waitFor(() => expect(cards()[COL_ERROR_RATE].textContent).toContain("<1%"));
    expect(cards()[COL_ERROR_RATE].querySelector(ERR_TONE_SELECTOR)).not.toBeNull();
  });

  it("shows an error rate just under 100% as >99%", async () => {
    serveHealth(createAppHealth({ error_rate: 99.7 }));
    const { cards } = renderStrip();
    await waitFor(() => expect(cards()[COL_ERROR_RATE].textContent).toContain(">99%"));
  });

  it("shows a recorded zero average as a duration, not a dash", async () => {
    serveHealth(createAppHealth({ handler_avg_duration_ms: 0, job_avg_duration_ms: 0 }));
    const { cards } = renderStrip();
    await waitFor(() => expect(cards()[COL_HANDLER_AVG].textContent).toContain("<1ms"));
    expect(cards()[COL_JOB_AVG].textContent).toContain("<1ms");
  });

  it("shows no tone and dashes for averages when nothing ran", async () => {
    serveHealth(createAppHealth());
    const { cards } = renderStrip();
    await waitFor(() => expect(cards()[COL_ERROR_RATE].textContent).toContain("0%"));
    expect(cards()[COL_ERROR_RATE].querySelector(ERR_TONE_SELECTOR)).toBeNull();
    expect(cards()[COL_HANDLER_AVG].textContent).toContain("—");
    expect(cards()[COL_JOB_AVG].textContent).toContain("—");
  });

  it("shows the error rate as unavailable when the health request fails", async () => {
    server.use(http.get(HEALTH_ROUTE, () => HttpResponse.json(null, { status: 503 })));
    const { cards } = renderStrip();
    await waitFor(() => expect(cards()[COL_ERROR_RATE].textContent).toContain("unavailable"));
    expect(cards()[COL_ERROR_RATE].querySelector(ERR_TONE_SELECTOR)).not.toBeNull();
  });

  it("refetches health when one of the app's executions completes", async () => {
    const requests = serveHealth(createAppHealth());
    renderStrip();
    await waitFor(() => expect(requests.length).toBe(1));

    act(() => {
      useAppStore.setState({
        executionCompleted: [createExecutionCompletedPayload({ kind: "handler", app_key: "my_app" })],
      });
    });

    await waitFor(() => expect(requests.length).toBeGreaterThan(1), { timeout: WS_DEBOUNCE_MAX_WAIT_MS });
  });

  it("drops the job average on small mobile", async () => {
    mockMediaQueryMatches(true);
    serveHealth(createAppHealth());
    const { cards, getByTestId } = renderStrip();
    await waitFor(() => expect(getByTestId(STRIP_TESTID).textContent).toContain("0%"));
    expect(cards().length).toBe(3);
  });
});
