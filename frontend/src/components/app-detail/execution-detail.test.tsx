import { QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { createExecution } from "../../test/factories";
import { createWouterMock } from "../../test/mock-wouter";
import { createTestQueryClient } from "../../test/query-test-utils";
import { server } from "../../test/server";
import { ExecutionDetailContent, ExecutionDetailFetcher } from "./execution-detail";

vi.mock("wouter", () => createWouterMock());

vi.mock("../shared/execution-logs", () => ({
  ExecutionLogs: ({ executionId }: { executionId: string }) => (
    <div data-testid="execution-logs">logs for {executionId}</div>
  ),
}));

vi.mock("../../hooks/use-document-title", () => ({
  useDocumentTitle: vi.fn(),
}));

function Wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={createTestQueryClient()}>{children}</QueryClientProvider>;
}

describe("ExecutionDetailContent", () => {
  it("renders truncated execution ID in heading", () => {
    const record = createExecution("handler", { execution_id: "abc12345-1234-5678-9abc-def012345678" });
    const { getByRole } = render(<ExecutionDetailContent record={record} />);
    expect(getByRole("heading").textContent).toContain("12345678");
  });

  it("renders full execution ID in code element", () => {
    const uuid = "abc12345-1234-5678-9abc-def012345678";
    const record = createExecution("handler", { execution_id: uuid });
    const { container } = render(<ExecutionDetailContent record={record} />);
    const code = container.querySelector("code");
    expect(code?.textContent).toBe(uuid);
  });

  it("renders meta stats with duration, timestamp, and status", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      duration_ms: 150,
      status: "success",
    });
    const { getByTestId } = render(<ExecutionDetailContent record={record} />);
    expect(getByTestId("execution-meta-stats")).toBeDefined();
  });

  it("renders success outcome banner for successful execution", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "success",
      duration_ms: 42,
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
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
    const { container } = render(<ExecutionDetailContent record={record} />);
    expect(container.textContent).toContain("failed");
  });

  it("renders traceback viewer for error with traceback", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "error",
      error_traceback: "Traceback (most recent call last):\n  File ...\nValueError: bad input",
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
    expect(container.textContent).toContain("Traceback");
  });

  it("renders timed out badge", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "timed_out",
      thread_leaked: false,
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
    expect(container.textContent).toContain("timed out");
  });

  it("renders thread leaked badge alongside timed out", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "timed_out",
      thread_leaked: true,
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
    expect(container.textContent).toContain("timed out");
    expect(container.textContent).toContain("thread leaked");
  });

  it("renders cancelled badge", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "cancelled",
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
    expect(container.textContent).toContain("cancelled");
  });

  it("renders skipped badge", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "skipped",
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
    // Scope to the badge element specifically — ErrorDisplay's resolveResultDisplay("skipped")
    // also renders the literal text "skipped", so a bare textContent check would pass even if
    // StatusBadge's "skipped" case were broken.
    const badges = Array.from(container.querySelectorAll('[data-slot="badge"]'));
    expect(badges.some((badge) => badge.textContent?.trim() === "skipped")).toBe(true);
  });

  it("renders trigger section when trigger_mode is present", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      trigger_mode: "manual",
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
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
    const { container } = render(<ExecutionDetailContent record={record} />);
    expect(container.textContent).toContain("context");
    expect(container.textContent).toContain("LOCAL");
  });

  it("does not render trigger section when no trigger fields", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      trigger_mode: null,
      trigger_context_id: null,
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
    expect(container.textContent).not.toContain("trigger");
  });

  it("renders ExecutionLogs component with execution ID", () => {
    const uuid = "abc12345-1234-5678-9abc-def012345678";
    const record = createExecution("handler", { execution_id: uuid });
    const { getByTestId } = render(<ExecutionDetailContent record={record} />);
    expect(getByTestId("execution-logs").textContent).toContain(uuid);
  });

  it("renders empty state when execution_id is null", () => {
    const record = createExecution("handler", { execution_id: null });
    const { container } = render(<ExecutionDetailContent record={record} />);
    expect(container.textContent).toContain("no execution ID");
  });

  it("copy button copies execution ID to clipboard", async () => {
    // userEvent.setup() unconditionally installs its own Clipboard API stub on
    // navigator.clipboard (a getter-only accessor), so it must run before we spy on
    // writeText -- spying on the stub's own method, rather than replacing the whole
    // clipboard object, avoids fighting that installation.
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    const uuid = "abc12345-1234-5678-9abc-def012345678";
    const record = createExecution("handler", { execution_id: uuid });

    const { container } = render(<ExecutionDetailContent record={record} />);
    const btn = container.querySelector("[aria-label='Copy execution ID']")!;
    await user.click(btn);

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(uuid));
  });

  it("renders ErrorDisplay for non-error failures without traceback", () => {
    const record = createExecution("handler", {
      execution_id: "abc12345-1234-5678-9abc-def012345678",
      status: "timed_out",
      error_type: "TimeoutError",
      error_message: "Handler exceeded deadline",
    });
    const { container } = render(<ExecutionDetailContent record={record} />);
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
        <ExecutionDetailFetcher executionId="abc-123" />
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
        <ExecutionDetailFetcher executionId="abc-123" />
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
        <ExecutionDetailFetcher executionId="abc-123" />
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
        <ExecutionDetailFetcher executionId="abc-123" />
      </Wrapper>,
    );
    expect(await findByText(/completed in/)).toBeDefined();
  });
});
