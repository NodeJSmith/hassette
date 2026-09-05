import { act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { Profiler } from "react";
import { describe, expect, it } from "vitest";

import type { components } from "../../api/generated-types";
import type { WsExecutionCompletedPayload } from "../../api/ws-types";
import { useAppStore } from "../../state/store";
import { createExecutionCompletedPayload } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";
import { server } from "../../test/server";
import type { ExecutionKind } from "../shared/execution-table";
import { RecentActivitySection } from "./recent-activity-section";

type ActivityFeedEntry = components["schemas"]["ActivityFeedEntry"];

function makeExecution(appKey: string, kind: ExecutionKind): WsExecutionCompletedPayload {
  return createExecutionCompletedPayload({ kind, app_key: appKey });
}

/**
 * Renders the section under a Profiler and waits for the initial fetch to commit.
 *
 * The Profiler counts commits of the subtree, so a store write that the section's selector
 * filters out produces no re-render and no count change — the seam these assertions need.
 */
async function renderSettled() {
  server.use(http.get("/api/telemetry/app/:app_key/activity", () => HttpResponse.json<ActivityFeedEntry[]>([])));
  const counter = { renders: 0 };
  const view = renderWithAppState(
    <Profiler
      id="recent-activity"
      onRender={() => {
        counter.renders += 1;
      }}
    >
      <RecentActivitySection appKey="test_app" resolvedInstanceIndex={0} />
    </Profiler>,
    { storeOverrides: { uptimeSeconds: 120 } },
  );
  await view.findByTestId("overview-activity-empty");
  await act(async () => {});
  return { ...view, counter };
}

describe("RecentActivitySection store subscriptions", () => {
  it("does not re-render on an unrelated app's execution completions", async () => {
    const { counter } = await renderSettled();
    const before = counter.renders;

    act(() => {
      useAppStore
        .getState()
        .setExecutionCompleted([makeExecution("other_app", "handler"), makeExecution("other_app", "job")]);
    });

    expect(counter.renders).toBe(before);
  });

  it.each(["handler", "job"] as const)("re-renders on its own app's %s execution completion", async (kind) => {
    const { counter } = await renderSettled();
    const before = counter.renders;

    act(() => {
      useAppStore.getState().setExecutionCompleted([makeExecution("test_app", kind)]);
    });

    await waitFor(() => expect(counter.renders).toBeGreaterThan(before));
  });
});
