import { fireEvent, screen } from "@testing-library/preact";
import { http, HttpResponse } from "msw";
import { h } from "preact";
import { describe, expect, it, vi } from "vitest";

import type { components } from "../../api/generated-types";
import { createInstance, createListener, createManifest } from "../../test/factories";
import { renderWithAppState } from "../../test/render-helpers";
import { server } from "../../test/server";
import { CommandPalette } from "./command-palette";

type ListenerWithSummary = components["schemas"]["ListenerWithSummary"];
type ManifestListResponse = components["schemas"]["AppManifestListResponse"];

// Mock wouter — factory cannot reference top-level variables (hoisting)
vi.mock("wouter", () => ({
  useLocation: vi.fn().mockReturnValue(["/", vi.fn()]),
  Link: ({ href, children, class: cls, ...rest }: Record<string, unknown>) =>
    h("a", { href, class: cls, ...rest }, children as never),
}));

// Import after mock is set up so useLocation is already mocked
const wouter = await import("wouter");
const mockNavigate = vi.fn();
(wouter.useLocation as ReturnType<typeof vi.fn>).mockReturnValue(["/", mockNavigate]);

function renderPalette(props: { open?: boolean; onClose?: () => void } = {}) {
  return renderWithAppState(<CommandPalette open={props.open ?? true} onClose={props.onClose ?? vi.fn()} />);
}

function withManifests(manifests: ReturnType<typeof createManifest>[]) {
  server.use(
    http.get("/api/apps/manifests", () =>
      HttpResponse.json<ManifestListResponse>({
        total: manifests.length,
        running: manifests.filter((m) => m.status === "running").length,
        failed: manifests.filter((m) => m.status === "failed").length,
        stopped: 0,
        disabled: 0,
        blocked: 0,
        manifests,
        only_app: null,
      }),
    ),
  );
}

describe("CommandPalette — open/close", () => {
  it("renders the palette overlay when open=true", () => {
    renderPalette({ open: true });
    expect(screen.getByRole("dialog")).toBeDefined();
  });

  it("does not render when open=false", () => {
    renderPalette({ open: false });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    renderPalette({ onClose });
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("calls onClose when backdrop is clicked", () => {
    const onClose = vi.fn();
    const { container } = renderPalette({ onClose });
    const backdrop = container.querySelector("[data-testid='cmd-palette-backdrop']")!;
    fireEvent.click(backdrop);
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("CommandPalette — structure", () => {
  it("renders an input with correct placeholder", () => {
    renderPalette();
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    expect(input).toBeDefined();
  });

  it("renders keyboard hints footer", () => {
    const { getByTestId } = renderPalette();
    const footer = getByTestId("cmd-palette-footer");
    expect(footer).not.toBeNull();
    expect(footer.textContent).toContain("navigate");
    expect(footer.textContent).toContain("select");
    expect(footer.textContent).toContain("close");
  });

  it("dialog has role=dialog and aria-modal", () => {
    renderPalette();
    const dialog = screen.getByRole("dialog");
    expect(dialog.getAttribute("aria-modal")).toBe("true");
  });
});

describe("CommandPalette — static items (pages and actions)", () => {
  it("shows page items when query is empty", async () => {
    renderPalette();
    expect(await screen.findByText("apps")).toBeDefined();
    expect(screen.getByText("logs")).toBeDefined();
    expect(screen.getByText("config")).toBeDefined();
  });

  it("shows action items when query is empty", async () => {
    renderPalette();
    expect(await screen.findByText("Reload all apps")).toBeDefined();
    expect(screen.getByText("Stop all failing")).toBeDefined();
    expect(screen.getByText("Open docs")).toBeDefined();
  });

  it("shows section headers for pages and actions", async () => {
    const { container } = renderPalette();
    await screen.findByText("apps");
    const headers = Array.from(container.querySelectorAll("[data-testid^='cmd-section-']")).map((el) =>
      el.getAttribute("data-testid")?.replace("cmd-section-", ""),
    );
    expect(headers).toContain("page");
    expect(headers).toContain("action");
  });
});

describe("CommandPalette — app items", () => {
  it("shows app items from manifests", async () => {
    withManifests([createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" })]);
    renderPalette();
    expect(await screen.findByText("Garage App")).toBeDefined();
  });

  it("shows section header for apps", async () => {
    withManifests([createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" })]);
    const { container } = renderPalette();
    await screen.findByText("Garage App");
    const headers = Array.from(container.querySelectorAll("[data-testid^='cmd-section-']")).map((el) =>
      el.getAttribute("data-testid")?.replace("cmd-section-", ""),
    );
    expect(headers).toContain("app");
  });

  it("shows instance items for multi-instance apps", async () => {
    withManifests([
      createManifest({
        app_key: "multi_app",
        display_name: "Multi App",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
          createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
        ],
      }),
    ]);
    renderPalette();
    expect(await screen.findByText("inst_0")).toBeDefined();
    expect(screen.getByText("inst_1")).toBeDefined();
  });

  it("navigates to /apps/:key?instance=N when instance item is selected", async () => {
    withManifests([
      createManifest({
        app_key: "multi_app",
        display_name: "Multi App",
        instance_count: 2,
        instances: [
          createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
          createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
        ],
      }),
    ]);
    const { container } = renderPalette();
    await screen.findByText("inst_1");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    fireEvent.input(input, { target: { value: "inst_1" } });
    await screen.findByText("inst_1");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const activeItem = container.querySelector("[aria-selected='true']");
    expect(activeItem?.textContent).toContain("inst_1");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/apps/multi_app?instance=1");
  });
});

describe("CommandPalette — filtering", () => {
  it("filters results to matching items when query is typed", async () => {
    withManifests([
      createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" }),
      createManifest({ app_key: "lights_app", display_name: "Lights App", status: "running" }),
    ]);
    renderPalette();
    await screen.findByText("Garage App");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    fireEvent.input(input, { target: { value: "garage" } });
    expect(screen.queryByText("Garage App")).not.toBeNull();
    expect(screen.queryByText("Lights App")).toBeNull();
  });

  it("hides section headers for sections with no matching results", async () => {
    withManifests([
      createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" }),
      createManifest({ app_key: "lights_app", display_name: "Lights App", status: "running" }),
    ]);
    const { container } = renderPalette();
    await screen.findByText("Garage App");
    const input = container.querySelector("input")!;
    fireEvent.input(input, { target: { value: "garage" } });
    const sections = Array.from(container.querySelectorAll("[data-testid^='cmd-section-']")).map((el) =>
      el.getAttribute("data-testid")?.replace("cmd-section-", ""),
    );
    expect(sections).not.toContain("page");
  });

  it("shows empty state when nothing matches", async () => {
    withManifests([
      createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" }),
      createManifest({ app_key: "lights_app", display_name: "Lights App", status: "running" }),
    ]);
    renderPalette();
    await screen.findByText("Garage App");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    fireEvent.input(input, { target: { value: "zzznomatch" } });
    expect(await screen.findByText(/no results/i)).toBeDefined();
  });
});

describe("CommandPalette — keyboard navigation", () => {
  it("pressing ArrowDown moves selection to next item", async () => {
    renderPalette();
    await screen.findByText("apps");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    // First item should now be selected — check for aria-selected
    const activeItems = document.querySelectorAll("[role='option'][aria-selected='true']");
    expect(activeItems.length).toBe(1);
  });

  it("pressing ArrowUp wraps back when at first item", async () => {
    renderPalette();
    await screen.findByText("apps");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    // Press down once to select first item, then up to go back to -1
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    const activeItems = document.querySelectorAll("[role='option'][aria-selected='true']");
    expect(activeItems.length).toBe(0);
  });
});

describe("CommandPalette — selection actions", () => {
  it("pressing Enter on a page item calls navigate", async () => {
    const { container } = renderPalette();
    await screen.findByText("apps");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    // Navigate to Apps item
    fireEvent.keyDown(input, { key: "ArrowDown" });
    // Find active item and confirm it's Apps
    const activeItem = container.querySelector("[role='option'][aria-selected='true']");
    expect(activeItem?.textContent).toContain("apps");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/apps");
  });

  it("pressing Enter on an app item navigates to app detail page", async () => {
    withManifests([createManifest({ app_key: "my_app", display_name: "My App", status: "running" })]);
    const { container } = renderPalette();
    await screen.findByText("My App");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    // Type to filter to only apps
    fireEvent.input(input, { target: { value: "My App" } });
    await screen.findByText("My App");
    // Arrow down to select the app item
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const activeItem = container.querySelector("[role='option'][aria-selected='true']");
    expect(activeItem?.textContent).toContain("My App");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/apps/my_app");
  });
});

describe("CommandPalette — type chips", () => {
  it("renders type chips for result items", async () => {
    renderPalette();
    await screen.findByText("apps");
    // Chips are the kind labels inside result buttons — check for "page" chip text
    const results = screen.getAllByRole("option");
    expect(results.length).toBeGreaterThan(0);
    // The first result (a page item) contains a "page" chip
    expect(results[0].textContent).toContain("page");
  });
});

describe("CommandPalette — handlers", () => {
  it("shows handler items when they are returned from the API", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json<ListenerWithSummary[]>([
          createListener({
            listener_id: 1,
            app_key: "my_app",
            instance_index: 0,
            handler_method: "on_state_change",
            topic: "state_changed",
          }),
        ]),
      ),
    );
    renderPalette();
    expect(await screen.findByText("on_state_change")).toBeDefined();
  });

  it("navigates to /apps/:key/handlers/listener/:id when handler item is selected", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json<ListenerWithSummary[]>([
          createListener({
            listener_id: 42,
            app_key: "my_app",
            handler_method: "on_state_change",
          }),
        ]),
      ),
    );
    const { container } = renderPalette();
    await screen.findByText("on_state_change");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    fireEvent.input(input, { target: { value: "on_state_change" } });
    await screen.findByText("on_state_change");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const activeItem = container.querySelector("[role='option'][aria-selected='true']");
    expect(activeItem?.textContent).toContain("on_state_change");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/apps/my_app/handlers/listener/42");
  });

  it("shows handlers section header when handlers are present", async () => {
    server.use(
      http.get("/api/bus/listeners", () =>
        HttpResponse.json<ListenerWithSummary[]>([
          createListener({ app_key: "my_app", handler_method: "on_state_change" }),
        ]),
      ),
    );
    const { container } = renderPalette();
    await screen.findByText("on_state_change");
    const sections = Array.from(container.querySelectorAll("[data-testid^='cmd-section-']")).map((el) =>
      el.getAttribute("data-testid")?.replace("cmd-section-", ""),
    );
    expect(sections).toContain("handler");
  });

  it("degrades gracefully when handler fetch fails", async () => {
    server.use(http.get("/api/bus/listeners", () => new HttpResponse(null, { status: 500 })));
    renderPalette();
    // Should still show pages and apps
    expect(await screen.findByText("apps")).toBeDefined();
  });

  it("does not fetch handlers when palette is closed (AC#7 enabled gate)", async () => {
    let callCount = 0;
    server.use(
      http.get("/api/bus/listeners", () => {
        callCount++;
        return HttpResponse.json<ListenerWithSummary[]>([
          createListener({ listener_id: 1, app_key: "my_app", handler_method: "on_state_change" }),
        ]);
      }),
    );

    // Closed palette — enabled: open suppresses the fetch entirely
    renderPalette({ open: false });
    // Flush any pending microtasks to confirm no fetch fires
    await new Promise((r) => setTimeout(r, 0));
    expect(callCount).toBe(0);
  });
});
