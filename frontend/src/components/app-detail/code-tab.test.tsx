import { render, screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "../../test/server";
import { CodeTab } from "./code-tab";

// Mock shiki to avoid async highlighting in tests
vi.mock("shiki", () => ({
  createHighlighter: vi.fn().mockResolvedValue({
    codeToHtml: vi.fn().mockImplementation((code: string) => {
      const lines = code.split("\n");
      const lineSpans = lines
        .map((line) => {
          const escaped = line.replace(/</g, "&lt;").replace(/>/g, "&gt;");
          return `<span class="line">${escaped}</span>`;
        })
        .join("\n");
      return `<pre class="shiki"><code>${lineSpans}</code></pre>`;
    }),
    dispose: vi.fn(),
  }),
}));

// Mock useQueryParams — controls the ?line= param for code-tab
let mockLineParam: string | null = null;
vi.mock("../../hooks/use-query-params", () => ({
  useQueryParams: () => ({
    get: (key: string) => (key === "line" ? mockLineParam : null),
    set: vi.fn(),
  }),
}));

// jsdom doesn't implement scrollIntoView — mock it globally
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// Long enough to observe the request in flight, short enough not to slow the suite.
const IN_FLIGHT_DELAY_MS = 100;

describe("CodeTab", () => {
  const defaultSource = {
    app_key: "test_app",
    filename: "test_app.py",
    content: "class TestApp:\n    def on_state_change(self):\n        pass\n",
    line_count: 3,
  };

  async function renderAndWaitForLoad(props: Partial<ComponentProps<typeof CodeTab>> = {}) {
    const result = render(<CodeTab appKey="test_app" listeners={[]} {...props} />);
    await waitFor(() => {
      expect(screen.getByTestId("code-tab-content")).toBeDefined();
    });
    return result;
  }

  beforeEach(() => {
    mockLineParam = null;
    server.use(
      http.get("/api/apps/:app_key/source", () => {
        return HttpResponse.json(defaultSource);
      }),
    );
  });

  it("shows loading spinner initially", () => {
    render(<CodeTab appKey="test_app" listeners={[]} />);
    expect(screen.getByRole("status")).toBeDefined();
  });

  it("renders source code after loading", async () => {
    await renderAndWaitForLoad();
  });

  it("includes Shiki token color utilities for light and dark themes", async () => {
    render(<CodeTab appKey="test_app" listeners={[]} />);
    const codeTab = await screen.findByTestId("code-tab-content");
    const body = codeTab.lastElementChild;
    expect(body?.className).toContain(
      "[&_.shiki_span:not(.line):not(.line-num)]:text-[var(--shiki-light,var(--ink-1))]",
    );
    expect(body?.className).toContain(
      "dark:[&_.shiki_span:not(.line):not(.line-num)]:text-[var(--shiki-dark,var(--ink-1))]",
    );
  });

  it("renders line numbers in gutter", async () => {
    await renderAndWaitForLoad();
    // Line numbers 1, 2, 3 should appear in gutter
    const gutterLines = screen.getAllByTestId(/^code-line-\d+$/);
    expect(gutterLines.length).toBeGreaterThanOrEqual(1);
  });

  it("shows error message when source file not found", async () => {
    server.use(
      http.get("/api/apps/:app_key/source", () => {
        return HttpResponse.json({ detail: "not found" }, { status: 404 });
      }),
    );
    render(<CodeTab appKey="test_app" listeners={[]} />);
    await waitFor(() => {
      expect(screen.getByTestId("code-tab-error")).toBeDefined();
    });
    expect(screen.getByTestId("code-tab-error").textContent).toContain("Source file not found");
  });

  it("shows line count in header", async () => {
    await renderAndWaitForLoad();
    expect(screen.getByTestId("code-tab-header").textContent).toContain(`${defaultSource.line_count} lines`);
  });

  it("shows read-only label in header", async () => {
    await renderAndWaitForLoad();
    expect(screen.getByTestId("code-tab-header").textContent).toContain("read-only");
  });

  it("shows copy path button in header", async () => {
    await renderAndWaitForLoad();
    expect(screen.getByTestId("copy-path-btn")).toBeDefined();
  });

  it("annotates handler lines with title tooltip on hover", async () => {
    const listeners = [
      {
        listener_id: 1,
        handler_method: "on_state_change",
        source_location: "test_app.py:2",
      },
    ];
    await renderAndWaitForLoad({ listeners: listeners as never });
    const line2 = screen.getByTestId("code-line-2");
    expect(line2.getAttribute("title")).toContain("on_state_change");
    expect(line2.classList.contains("line--annotated")).toBe(true);
  });

  // CodeTab reads ?line= from URL instead of focusLine prop
  it("reads focusLine from ?line= query param and applies line--focus class", async () => {
    mockLineParam = "2";
    await renderAndWaitForLoad();
    // Wait for the focus effect to run
    await waitFor(() => {
      const line2 = screen.getByTestId("code-line-2");
      expect(line2.classList.contains("line--focus")).toBe(true);
    });
  });

  it("does not apply line--focus class when ?line= is absent", async () => {
    mockLineParam = null;
    await renderAndWaitForLoad();
    const line1 = screen.getByTestId("code-line-1");
    expect(line1.classList.contains("line--focus")).toBe(false);
  });

  it("aborts in-flight request on unmount", async () => {
    let requestSignal: AbortSignal | undefined;

    server.use(
      http.get("/api/apps/:app_key/source", async ({ request }) => {
        requestSignal = request.signal;
        await delay(IN_FLIGHT_DELAY_MS);
        return HttpResponse.json(defaultSource);
      }),
    );

    const { unmount } = render(<CodeTab appKey="test_app" listeners={[]} />);
    expect(screen.getByRole("status")).toBeDefined();

    // Wait for the request to be initiated
    await waitFor(() => expect(requestSignal).toBeDefined());
    unmount();

    expect(requestSignal!.aborted).toBe(true);
  });
});
