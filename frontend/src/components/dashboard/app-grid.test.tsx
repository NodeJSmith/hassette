import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { AppGrid } from "./app-grid";
import { createAppGridEntry } from "../../test/factories";

vi.mock("../../hooks/use-relative-time", () => ({
  useRelativeTime: () => "2m ago",
}));

describe("AppGrid", () => {
  it("returns null when apps is null", () => {
    const { container } = render(<AppGrid apps={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders empty state when apps list is empty", () => {
    const { getByText } = render(<AppGrid apps={[]} />);
    expect(getByText("No apps registered.")).toBeDefined();
  });

  it("renders a card for each active app", () => {
    const apps = [
      createAppGridEntry({ app_key: "app_a", display_name: "App A", status: "running" }),
      createAppGridEntry({ app_key: "app_b", display_name: "App B", status: "running" }),
    ];
    const { container } = render(<AppGrid apps={apps} />);
    const cards = container.querySelectorAll(".ht-app-card");
    expect(cards.length).toBe(2);
  });

  it("renders one card for a single app", () => {
    const apps = [createAppGridEntry({ app_key: "sole_app", display_name: "Sole App", status: "running" })];
    const { container } = render(<AppGrid apps={apps} />);
    const cards = container.querySelectorAll(".ht-app-card");
    expect(cards.length).toBe(1);
  });

  it("separates active and inactive apps into sections", () => {
    const apps = [
      createAppGridEntry({ app_key: "active_app", display_name: "Active", status: "running" }),
      createAppGridEntry({ app_key: "stopped_app", display_name: "Stopped", status: "stopped" }),
    ];
    const { getByText } = render(<AppGrid apps={apps} />);
    expect(getByText("Inactive")).toBeDefined();
  });

  it("does not show Inactive heading when all apps are active", () => {
    const apps = [
      createAppGridEntry({ app_key: "app_a", display_name: "App A", status: "running" }),
    ];
    const { queryByText } = render(<AppGrid apps={apps} />);
    expect(queryByText("Inactive")).toBeNull();
  });

  it("shows Inactive heading when only inactive apps exist", () => {
    const apps = [
      createAppGridEntry({ app_key: "stopped_app", display_name: "Stopped", status: "stopped" }),
    ];
    const { queryByText } = render(<AppGrid apps={apps} />);
    expect(queryByText("Inactive")).not.toBeNull();
  });

  it("inactive section shows disabled and stopped apps", () => {
    const apps = [
      createAppGridEntry({ app_key: "stopped_app", display_name: "Stopped App", status: "stopped" }),
      createAppGridEntry({ app_key: "disabled_app", display_name: "Disabled App", status: "disabled" }),
    ];
    const { container } = render(<AppGrid apps={apps} />);
    const inactiveGrid = container.querySelector(".ht-app-grid--inactive");
    expect(inactiveGrid).not.toBeNull();
    const cards = inactiveGrid!.querySelectorAll(".ht-app-card");
    expect(cards.length).toBe(2);
  });

  it("passes app data to AppCard children", () => {
    const apps = [
      createAppGridEntry({ app_key: "my_app", display_name: "My Automation", status: "running" }),
    ];
    const { getByText } = render(<AppGrid apps={apps} />);
    expect(getByText("My Automation")).toBeDefined();
  });

  it("sorts active apps alphabetically by display name", () => {
    const apps = [
      createAppGridEntry({ app_key: "z_app", display_name: "Zebra App", status: "running" }),
      createAppGridEntry({ app_key: "a_app", display_name: "Apple App", status: "running" }),
    ];
    const { container } = render(<AppGrid apps={apps} />);
    const activeGrid = container.querySelector(".ht-app-grid:not(.ht-app-grid--inactive)");
    expect(activeGrid).not.toBeNull();
    const cards = Array.from(activeGrid!.querySelectorAll(".ht-app-card"));
    expect(cards[0].getAttribute("data-testid")).toBe("app-card-a_app");
    expect(cards[1].getAttribute("data-testid")).toBe("app-card-z_app");
  });

  it("failed apps appear in the active (not inactive) section", () => {
    const apps = [
      createAppGridEntry({ app_key: "failed_app", display_name: "Failed App", status: "failed" }),
    ];
    const { container, queryByText } = render(<AppGrid apps={apps} />);
    // failed is not an INACTIVE_STATUS — it should appear in the active grid
    expect(queryByText("Inactive")).toBeNull();
    const activeGrid = container.querySelector(".ht-app-grid");
    expect(activeGrid).not.toBeNull();
  });
});
