import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { server } from "../../test/server";

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

import { CodeTab } from "./code-tab";

describe("CodeTab", () => {
  const defaultSource = {
    app_key: "test_app",
    filename: "test_app.py",
    content: "class TestApp:\n    def on_state_change(self):\n        pass\n",
    line_count: 3,
  };

  beforeEach(() => {
    server.use(
      http.get("/api/apps/:app_key/source", () => {
        return HttpResponse.json(defaultSource);
      }),
    );
  });

  it("shows loading spinner initially", () => {
    render(<CodeTab appKey="test_app" listeners={[]} />);
    expect(screen.getByTestId("code-tab-loading")).toBeDefined();
  });

  it("renders source code after loading", async () => {
    render(<CodeTab appKey="test_app" listeners={[]} />);
    await waitFor(() => {
      expect(screen.getByTestId("code-tab-content")).toBeDefined();
    });
  });

  it("renders line numbers in gutter", async () => {
    render(<CodeTab appKey="test_app" listeners={[]} />);
    await waitFor(() => {
      expect(screen.getByTestId("code-tab-content")).toBeDefined();
    });
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
    expect(screen.getByTestId("code-tab-error").textContent).toContain(
      "Source file not found",
    );
  });

  it("shows line count in header", async () => {
    render(<CodeTab appKey="test_app" listeners={[]} />);
    await waitFor(() => {
      expect(screen.getByTestId("code-tab-content")).toBeDefined();
    });
    // "class TestApp:\n    def on_state_change(self):\n        pass\n" = 3 lines
    expect(screen.getByTestId("code-tab-header").textContent).toContain("3 lines");
  });

  it("shows read-only label in header", async () => {
    render(<CodeTab appKey="test_app" listeners={[]} />);
    await waitFor(() => {
      expect(screen.getByTestId("code-tab-content")).toBeDefined();
    });
    expect(screen.getByTestId("code-tab-header").textContent).toContain("read-only");
  });

  it("shows copy path button in header", async () => {
    render(<CodeTab appKey="test_app" listeners={[]} />);
    await waitFor(() => {
      expect(screen.getByTestId("code-tab-content")).toBeDefined();
    });
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
    render(<CodeTab appKey="test_app" listeners={listeners as never} />);
    await waitFor(() => {
      expect(screen.getByTestId("code-tab-content")).toBeDefined();
    });
    const line2 = screen.getByTestId("code-line-2");
    expect(line2.getAttribute("title")).toContain("on_state_change");
    expect(line2.classList.contains("line--annotated")).toBe(true);
  });
});
