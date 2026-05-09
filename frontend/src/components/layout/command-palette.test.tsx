import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/preact";
import { h } from "preact";
import { server } from "../../test/server";
import { http, HttpResponse } from "msw";
import { createManifest, createManifestList, createInstance, createListener } from "../../test/factories";
import type { components } from "../../api/generated-types";
import { AppStateContext } from "../../state/context";
import { createAppState } from "../../state/create-app-state";

type ManifestListResponse = components["schemas"]["AppManifestListResponse"];
type ListenerWithSummary = components["schemas"]["ListenerWithSummary"];

// Mock wouter
const mockNavigate = vi.fn();
vi.mock("wouter", () => ({
  useLocation: vi.fn().mockReturnValue(["/", mockNavigate]),
  Link: ({ href, children, class: cls, ...rest }: Record<string, unknown>) =>
    h("a", { href, class: cls, ...rest }, children as never),
}));

// Import after mock is set up
const { CommandPalette } = await import("./command-palette");

function renderPalette(props: { open?: boolean; onClose?: () => void } = {}) {
  const state = createAppState();
  return render(
    <AppStateContext.Provider value={state}>
      <CommandPalette open={props.open ?? true} onClose={props.onClose ?? vi.fn()} />
    </AppStateContext.Provider>,
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
    const backdrop = container.querySelector(".ht-cmd-palette__backdrop")!;
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
    const { container } = renderPalette();
    const footer = container.querySelector(".ht-cmd-palette__footer");
    expect(footer).not.toBeNull();
    expect(footer!.textContent).toContain("navigate");
    expect(footer!.textContent).toContain("select");
    expect(footer!.textContent).toContain("close");
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
    expect(await screen.findByText("Apps")).toBeDefined();
    expect(screen.getByText("Logs")).toBeDefined();
    expect(screen.getByText("Config")).toBeDefined();
  });

  it("shows action items when query is empty", async () => {
    renderPalette();
    expect(await screen.findByText("Reload all apps")).toBeDefined();
    expect(screen.getByText("Stop all failing")).toBeDefined();
    expect(screen.getByText("Open docs")).toBeDefined();
  });

  it("shows section headers for pages and actions", async () => {
    const { container } = renderPalette();
    await screen.findByText("Apps");
    const headers = Array.from(container.querySelectorAll(".ht-cmd-palette__section-header")).map(
      (el) => el.textContent,
    );
    expect(headers).toContain("pages");
    expect(headers).toContain("actions");
  });
});

describe("CommandPalette — app items", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" }),
            ],
          }),
        ),
      ),
    );
  });

  it("shows app items from manifests", async () => {
    renderPalette();
    expect(await screen.findByText("Garage App")).toBeDefined();
  });

  it("shows section header for apps", async () => {
    const { container } = renderPalette();
    await screen.findByText("Garage App");
    const headers = Array.from(container.querySelectorAll(".ht-cmd-palette__section-header")).map(
      (el) => el.textContent,
    );
    expect(headers).toContain("apps");
  });

  it("shows instance items for multi-instance apps", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({
                app_key: "multi_app",
                display_name: "Multi App",
                instance_count: 2,
                instances: [
                  createInstance({ app_key: "multi_app", index: 0, instance_name: "inst_0" }),
                  createInstance({ app_key: "multi_app", index: 1, instance_name: "inst_1" }),
                ],
              }),
            ],
          }),
        ),
      ),
    );
    renderPalette();
    expect(await screen.findByText("inst_0")).toBeDefined();
    expect(screen.getByText("inst_1")).toBeDefined();
  });
});

describe("CommandPalette — filtering", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "garage_app", display_name: "Garage App", status: "running" }),
              createManifest({ app_key: "lights_app", display_name: "Lights App", status: "running" }),
            ],
          }),
        ),
      ),
    );
  });

  it("filters results to matching items when query is typed", async () => {
    renderPalette();
    await screen.findByText("Garage App");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    fireEvent.input(input, { target: { value: "garage" } });
    expect(screen.queryByText("Garage App")).not.toBeNull();
    expect(screen.queryByText("Lights App")).toBeNull();
  });

  it("hides section headers for sections with no matching results", async () => {
    renderPalette();
    await screen.findByText("Garage App");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    // Search for something only matching apps, not pages/actions
    fireEvent.input(input, { target: { value: "garage" } });
    const { container } = renderPalette();
    // Re-render after input is typed in first render
    fireEvent.input(container.querySelector("input")!, { target: { value: "garage" } });
    const headers = Array.from(container.querySelectorAll(".ht-cmd-palette__section-header")).map(
      (el) => el.textContent?.toLowerCase(),
    );
    // Pages section header should not appear (no page matches "garage")
    expect(headers).not.toContain("pages");
  });

  it("shows empty state when nothing matches", async () => {
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
    await screen.findByText("Apps");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    // First item should now be selected — check for ht-cmd-palette__result--active
    const activeItems = document.querySelectorAll(".ht-cmd-palette__result--active");
    expect(activeItems.length).toBe(1);
  });

  it("pressing ArrowUp wraps back when at first item", async () => {
    renderPalette();
    await screen.findByText("Apps");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    // Press down once to select first item, then up to go back to -1
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    const activeItems = document.querySelectorAll(".ht-cmd-palette__result--active");
    expect(activeItems.length).toBe(0);
  });
});

describe("CommandPalette — selection actions", () => {
  it("pressing Enter on a page item calls navigate", async () => {
    const { container } = renderPalette();
    await screen.findByText("Apps");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    // Navigate to Apps item
    fireEvent.keyDown(input, { key: "ArrowDown" });
    // Find active item and confirm it's Apps
    const activeItem = container.querySelector(".ht-cmd-palette__result--active");
    expect(activeItem?.textContent).toContain("Apps");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/apps");
  });

  it("pressing Enter on an app item navigates to app detail page", async () => {
    server.use(
      http.get("/api/apps/manifests", () =>
        HttpResponse.json<ManifestListResponse>(
          createManifestList({
            manifests: [
              createManifest({ app_key: "my_app", display_name: "My App", status: "running" }),
            ],
          }),
        ),
      ),
    );
    const { container } = renderPalette();
    await screen.findByText("My App");
    const input = screen.getByPlaceholderText("Search apps, handlers, pages, actions…");
    // Type to filter to only apps
    fireEvent.input(input, { target: { value: "My App" } });
    await screen.findByText("My App");
    // Arrow down to select the app item
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const activeItem = container.querySelector(".ht-cmd-palette__result--active");
    expect(activeItem?.textContent).toContain("My App");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalledWith("/apps/my_app");
  });
});

describe("CommandPalette — type chips", () => {
  it("renders type chips for result items", async () => {
    const { container } = renderPalette();
    await screen.findByText("Apps");
    const chips = container.querySelectorAll(".ht-cmd-palette__chip");
    expect(chips.length).toBeGreaterThan(0);
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
    const headers = Array.from(container.querySelectorAll(".ht-cmd-palette__section-header")).map(
      (el) => el.textContent,
    );
    expect(headers).toContain("handlers");
  });

  it("degrades gracefully when handler fetch fails", async () => {
    server.use(
      http.get("/api/bus/listeners", () => HttpResponse.error()),
    );
    renderPalette();
    // Should still show pages and apps
    expect(await screen.findByText("Apps")).toBeDefined();
  });
});
