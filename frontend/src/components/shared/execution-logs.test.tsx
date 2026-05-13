import { describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";
import { ExecutionLogs } from "./execution-logs";
import { createLogEntry } from "../../test/factories";
import type { components } from "../../api/generated-types";

type LogsByExecutionResponse = components["schemas"]["LogsByExecutionResponse"];

vi.mock("./log-table", () => ({
  LogTable: ({ fetcher }: { fetcher?: () => Promise<unknown> }) => (
    <div data-testid="log-table-stub" data-has-fetcher={String(!!fetcher)} />
  ),
}));

describe("ExecutionLogs", () => {
  it("shows loading state initially", () => {
    const { getByText } = render(<ExecutionLogs executionId="test-id" />);
    expect(getByText("Loading logs…")).toBeDefined();
  });

  it("shows empty state when no records returned", async () => {
    const { getByText } = render(<ExecutionLogs executionId="empty-id" />);
    await waitFor(() => {
      expect(getByText("No logs recorded for this execution.")).toBeDefined();
    });
  });

  it("shows retention expired message", async () => {
    server.use(
      http.get("/api/logs/by-execution/:id", () =>
        HttpResponse.json<LogsByExecutionResponse>({
          records: [],
          truncated: false,
          retention_expired: true,
        }),
      ),
    );

    const { getByText } = render(<ExecutionLogs executionId="expired-id" />);
    await waitFor(() => {
      expect(getByText(/deleted by retention policy/)).toBeDefined();
    });
  });

  it("shows error state on fetch failure", async () => {
    server.use(
      http.get("/api/logs/by-execution/:id", () =>
        HttpResponse.error(),
      ),
    );

    const { getByText } = render(<ExecutionLogs executionId="fail-id" />);
    await waitFor(() => {
      expect(getByText("Failed to load logs.")).toBeDefined();
    });
  });

  it("renders LogTable when records are returned", async () => {
    server.use(
      http.get("/api/logs/by-execution/:id", () =>
        HttpResponse.json<LogsByExecutionResponse>({
          records: [createLogEntry({ message: "test log" })],
          truncated: false,
          retention_expired: false,
        }),
      ),
    );

    const { getByTestId } = render(<ExecutionLogs executionId="loaded-id" />);
    await waitFor(() => {
      expect(getByTestId("log-table-stub")).toBeDefined();
    });
  });

  it("shows truncation notice when truncated", async () => {
    server.use(
      http.get("/api/logs/by-execution/:id", () =>
        HttpResponse.json<LogsByExecutionResponse>({
          records: [createLogEntry()],
          truncated: true,
          retention_expired: false,
        }),
      ),
    );

    const { getByText } = render(<ExecutionLogs executionId="trunc-id" />);
    await waitFor(() => {
      expect(getByText(/Showing first/)).toBeDefined();
    });
  });

  it("renders view-all-logs link with correct href", async () => {
    server.use(
      http.get("/api/logs/by-execution/:id", () =>
        HttpResponse.json<LogsByExecutionResponse>({
          records: [createLogEntry()],
          truncated: false,
          retention_expired: false,
        }),
      ),
    );

    const { getByTestId } = render(<ExecutionLogs executionId="abc-123" />);
    await waitFor(() => {
      const link = getByTestId("view-all-logs-link") as HTMLAnchorElement;
      expect(link.getAttribute("href")).toBe("/logs?execution_id=abc-123");
    });
  });
});
