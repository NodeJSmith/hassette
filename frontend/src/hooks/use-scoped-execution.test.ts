import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { WsExecutionCompletedPayload } from "../api/ws-types";
import { useAppStore } from "../state/store";
import { useAppExecution, useJobExecution, useListenerExecution } from "./use-scoped-execution";

function handlerCompletion(appKey: string, listenerId: number): WsExecutionCompletedPayload {
  return {
    kind: "handler",
    app_key: appKey,
    instance_index: 0,
    status: "success",
    duration_ms: 5,
    listener_id: listenerId,
  };
}

function jobCompletion(appKey: string, jobId: number): WsExecutionCompletedPayload {
  return { kind: "job", app_key: appKey, instance_index: 0, status: "success", duration_ms: 5, job_id: jobId };
}

/** Renders `hook` while counting how many times it re-ran — the seam for the scoping assertions. */
function renderCounted<T>(hook: () => T) {
  const counter = { renders: 0 };
  const view = renderHook(() => {
    counter.renders += 1;
    return hook();
  });
  return { ...view, counter };
}

function publish(...events: WsExecutionCompletedPayload[]) {
  act(() => {
    useAppStore.getState().setExecutionCompleted(events);
  });
}

describe("useAppExecution", () => {
  it("does not re-render on another app's completions", () => {
    const { result, counter } = renderCounted(() => useAppExecution("test_app"));
    const before = counter.renders;

    publish(handlerCompletion("other_app", 1), jobCompletion("other_app", 2));

    expect(counter.renders).toBe(before);
    expect(result.current).toBeUndefined();
  });

  it("returns this app's matching record", () => {
    const { result, counter } = renderCounted(() => useAppExecution("test_app"));
    const before = counter.renders;
    const own = handlerCompletion("test_app", 1);

    publish(handlerCompletion("other_app", 9), own);

    expect(counter.renders).toBeGreaterThan(before);
    expect(result.current).toBe(own);
  });

  it("ignores this app's completions of the other kind when narrowed", () => {
    const { result, counter } = renderCounted(() => useAppExecution("test_app", "handler"));
    const before = counter.renders;

    publish(jobCompletion("test_app", 3));

    expect(counter.renders).toBe(before);
    expect(result.current).toBeUndefined();
  });

  it("re-renders on each consecutive own completion", () => {
    const { counter } = renderCounted(() => useAppExecution("test_app"));

    publish(handlerCompletion("test_app", 1));
    const afterFirst = counter.renders;
    publish(handlerCompletion("test_app", 1));

    expect(counter.renders).toBeGreaterThan(afterFirst);
  });
});

describe("useJobExecution", () => {
  it("does not re-render on another job's completions", () => {
    const { result, counter } = renderCounted(() => useJobExecution(7));
    const before = counter.renders;

    publish(jobCompletion("test_app", 8), handlerCompletion("test_app", 7));

    expect(counter.renders).toBe(before);
    expect(result.current).toBeUndefined();
  });

  it("returns this job's matching record", () => {
    const { result, counter } = renderCounted(() => useJobExecution(7));
    const before = counter.renders;
    const own = jobCompletion("test_app", 7);

    publish(jobCompletion("test_app", 8), own);

    expect(counter.renders).toBeGreaterThan(before);
    expect(result.current).toBe(own);
  });
});

describe("useListenerExecution", () => {
  it("does not re-render on another listener's completions", () => {
    const { result, counter } = renderCounted(() => useListenerExecution(4));
    const before = counter.renders;

    publish(handlerCompletion("test_app", 5), jobCompletion("test_app", 4));

    expect(counter.renders).toBe(before);
    expect(result.current).toBeUndefined();
  });

  it("returns this listener's matching record", () => {
    const { result, counter } = renderCounted(() => useListenerExecution(4));
    const before = counter.renders;
    const own = handlerCompletion("test_app", 4);

    publish(handlerCompletion("test_app", 5), own);

    expect(counter.renders).toBeGreaterThan(before);
    expect(result.current).toBe(own);
  });
});
