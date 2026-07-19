import { QueryClientProvider } from "@tanstack/preact-query";
import { fireEvent, render, waitFor } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import type { ComponentChildren } from "preact";
import { describe, expect, it, vi } from "vitest";

import { createExecution } from "../../test/factories";
import { createTestQueryClient } from "../../test/query-test-utils";
import { server } from "../../test/server";
import { ExecutionDetailContent, ExecutionDetailFetcher } from "./execution-detail";

vi.mock("wouter", () => ({
  Link: ({ href, children, class: cls }: Record<string, unknown>) => (
    <a href={href as string} class={cls as string}>
      {children as never}
    </a>
  ),
}));

vi.mock("../shared/execution-logs", () => ({
  ExecutionLogs: ({ executionId }: { executionId: string }) => (
    <div data-testid="execution-logs">logs for {executionId}</div>
  ),
}));

vi.mock("../../hooks/use-document-title", () => ({
  useDocumentTitle: vi.fn(),
}));

function Wrapper({ children }: { children: ComponentChildren }) {
  return <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>;
}

describe("ExecutionDetailContent", () => {
  const backHref = "/apps/my_app/handlers/listener/1";

  it("renders back link with handler name", () => {
    const record = createExecution("handler", { execution_id: "abc12345-1234-5678-9abc-def012345678" });
    const { getByText } = render(<ExecutionDetailContent record={record} backHref={backHref} handlerName="on_light" />);
    const link = getByText("← back to on_light");
    expect(link.getAttribute("href")).toBe(backHref);
  });

  it("renders back link with default text when no handlerName", () => {
    const record = createExecution("handler", { execution_id: "abc12345-1234-5678-9abc-def012345678" });
    const { getByText } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(getByText("← back to handler")).toBeDefined();
  });

  it("renders truncated execution ID in heading", () => {
    const record = createExecution("handler", { execution_id: "abc12345-1234-5678-9abc-def012345678" });
    const { getByRole } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(getByRole("heading").textContent).toContain("12345678");
  });

  it("renders full execution ID in code element", () => {
    const uuid = "abc12345-1234-5678-9abc-def012345678";
    const record = createExecution("handler", { execution_id: uuid });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    const code = container.querySelector("code");
    expect(code?.textContent).toBe(uuid);
  });

  it("renders meta stats with duration, timestamp, and status", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      duration_ms: 150,
      status: "success",
    });
    const { getByTestId } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(getByTestId("execution-meta-stats")).toBeDefined();
  });

  it("renders success outcome banner for successful execution", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "success",
      duration_ms: 42,
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("completed in");
  });

  it("renders failed badge for error status", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "error",
      error_type: "ValueError",
      error_message: "bad input",
      error_traceback: "Traceback (most recent call last):\n  File ...\nValueError: bad input",
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("failed");
  });

  it("renders traceback viewer for error with traceback", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "error",
      error_traceback: "Traceback (most recent call last):\n  File ...\nValueError: bad input",
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("Traceback");
  });

  it("renders timed out badge", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "timed_out",
      thread_leaked: false,
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("timed out");
  });

  it("renders thread leaked badge alongside timed out", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "timed_out",
      thread_leaked: true,
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("timed out");
    expect(container.textContent).toContain("thread leaked");
  });

  it("renders cancelled badge", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "cancelled",
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("cancelled");
  });

  it("renders trigger section when trigger_mode is present", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      trigger_mode: "manual",
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("trigger");
    expect(container.textContent).toContain("manual");
  });

  it("renders trigger context and origin when present", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      trigger_context_id: "ctx-abc12345-long-uuid-value",
      trigger_origin: "LOCAL",
      trigger_mode: "event",
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("context");
    expect(container.textContent).toContain("LOCAL");
  });

  it("does not render trigger section when no trigger fields", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      trigger_mode: null,
      trigger_context_id: null,
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).not.toContain("trigger");
  });

  it("renders ExecutionLogs component with execution ID", () => {
    const uuid = "abc12345-1234-5678-9abc-def012345678";
    const record = createExecution("handler", { execution_id: uuid });
    const { getByTestId } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(getByTestId("execution-logs").textContent).toContain(uuid);
  });

  it("renders empty state when execution_id is null", () => {
    const record = createExecution("handler", { execution_id: null });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).toContain("no execution ID");
  });

  it("copy button copies execution ID to clipboard", async () => {
    const uuid = "abc12345-1234-5678-9abc-def012345678";
    const record = createExecution("handler", { execution_id: uuid });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    const btn = container.querySelector("[aria-label='Copy execution ID']")!;
    fireEvent.click(btn);

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(uuid));
  });

  it("renders ErrorDisplay for non-error failures without traceback", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "timed_out",
      error_type: "TimeoutError",
      error_message: "Handler exceeded deadline",
    });
    const { container } = render(<ExecutionDetailContent record={record} backHref={backHref} />);
    expect(container.textContent).not.toContain("completed in");
  });
});

describe("ExecutionDetailFetcher", () => {
  it("renders spinner while loading", () => {
    server.use(
      http.get("/api/telemetry/execution/:id", async () => {
        await new Promise(() => {});
      }),
    );
    const { container } = render(
      <Wrapper>
        <ExecutionDetailFetcher appKey="my_app" kind="listener" handlerId={1} executionId="abc-123" instanceQs="" />
      </Wrapper>,
    );
    expect(container.querySelector("[role='status']")).not.toBeNull();
  });

  it("renders error state on fetch failure", async () => {
    server.use(
      http.get("/api/telemetry/execution/:id", () => {
        return HttpResponse.error();
      }),
    );
    const { findByText } = render(
      <Wrapper>
        <ExecutionDetailFetcher appKey="my_app" kind="listener" handlerId={1} executionId="abc-123" instanceQs="" />
      </Wrapper>,
    );
    expect(await findByText("failed to load execution")).toBeDefined();
  });

  it("renders not-found state when response is null", async () => {
    server.use(
      http.get("/api/telemetry/execution/:id", () => {
        return HttpResponse.json(null);
      }),
    );
    const { findByText } = render(
      <Wrapper>
        <ExecutionDetailFetcher appKey="my_app" kind="listener" handlerId={1} executionId="abc-123" instanceQs="" />
      </Wrapper>,
    );
    expect(await findByText("execution not found")).toBeDefined();
  });

  it("renders execution detail content on successful fetch", async () => {
    const execution = createExecution("handler", {
      execution_id: "abc-123",
      status: "success",
      duration_ms: 42,
    });
    server.use(
      http.get("/api/telemetry/execution/:id", () => {
        return HttpResponse.json(execution);
      }),
    );
    const { findByText } = render(
      <Wrapper>
        <ExecutionDetailFetcher appKey="my_app" kind="listener" handlerId={1} executionId="abc-123" instanceQs="" />
      </Wrapper>,
    );
    expect(await findByText(/completed in/)).toBeDefined();
  });

  it("builds correct back href with instance query string", async () => {
    const execution = createExecution("handler", { execution_id: "abc-123", status: "success" });
    server.use(
      http.get("/api/telemetry/execution/:id", () => {
        return HttpResponse.json(execution);
      }),
    );
    const { findByText } = render(
      <Wrapper>
        <ExecutionDetailFetcher
          appKey="my_app"
          kind="listener"
          handlerId={5}
          executionId="abc-123"
          instanceQs="?instance=2"
          handlerName="on_motion"
        />
      </Wrapper>,
    );
    const link = await findByText("← back to on_motion");
    expect(link.getAttribute("href")).toBe("/apps/my_app/handlers/listener/5?instance=2");
  });

  it("error state back link uses correct href", async () => {
    server.use(
      http.get("/api/telemetry/execution/:id", () => {
        return HttpResponse.error();
      }),
    );
    const { findByText } = render(
      <Wrapper>
        <ExecutionDetailFetcher
          appKey="my_app"
          kind="job"
          handlerId={3}
          executionId="abc-123"
          instanceQs=""
          handlerName="daily_check"
        />
      </Wrapper>,
    );
    const link = await findByText("← back to daily_check");
    expect(link.getAttribute("href")).toBe("/apps/my_app/handlers/job/3");
  });
});
