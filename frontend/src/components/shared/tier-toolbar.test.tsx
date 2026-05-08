import { describe, expect, it, vi } from "vitest";
import { render, fireEvent } from "@testing-library/preact";
import { TierToolbar } from "./tier-toolbar";

describe("TierToolbar", () => {
  // -- Tier toggle --

  it("renders All, Apps, Framework tier buttons", () => {
    const { getByRole } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    expect(getByRole("button", { name: /^all$/i })).toBeDefined();
    expect(getByRole("button", { name: /^apps$/i })).toBeDefined();
    expect(getByRole("button", { name: /^framework$/i })).toBeDefined();
  });

  it("marks the active tier button with --active class", () => {
    const { getByRole } = render(
      <TierToolbar
        tierFilter="app"
        onTierChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    const appsBtn = getByRole("button", { name: /^apps$/i });
    expect(appsBtn.classList.contains("ht-tier-toggle__btn--active")).toBe(true);
    const allBtn = getByRole("button", { name: /^all$/i });
    expect(allBtn.classList.contains("ht-tier-toggle__btn--active")).toBe(false);
  });

  it("calls onTierChange with the clicked tier value", () => {
    const onTierChange = vi.fn();
    const { getByRole } = render(
      <TierToolbar
        tierFilter="app"
        onTierChange={onTierChange}
        testIdPrefix="test"
      />,
    );
    fireEvent.click(getByRole("button", { name: /^framework$/i }));
    expect(onTierChange).toHaveBeenCalledWith("framework");
  });

  it("uses testIdPrefix for tier toggle data-testid", () => {
    const { getByTestId } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        testIdPrefix="handlers"
      />,
    );
    expect(getByTestId("handlers-tier-toggle")).toBeDefined();
  });

  // -- App filter --

  it("renders app filter when appKeys and onAppChange are provided", () => {
    const { getByTestId } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        appKeys={["app_a", "app_b"]}
        selectedApp=""
        onAppChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    expect(getByTestId("test-app-filter")).toBeDefined();
  });

  it("does not render app filter when appKeys is not provided", () => {
    const { queryByTestId } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    expect(queryByTestId("test-app-filter")).toBeNull();
  });

  it("does not render app filter when appKeys is empty", () => {
    const { queryByTestId } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        appKeys={[]}
        onAppChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    expect(queryByTestId("test-app-filter")).toBeNull();
  });

  it("calls onAppChange with the selected value", () => {
    const onAppChange = vi.fn();
    const { getByTestId } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        appKeys={["app_a", "app_b"]}
        selectedApp=""
        onAppChange={onAppChange}
        testIdPrefix="test"
      />,
    );
    fireEvent.change(getByTestId("test-app-filter"), { target: { value: "app_a" } });
    expect(onAppChange).toHaveBeenCalledWith("app_a");
  });

  it("shows app label with selected app name", () => {
    const { getByText } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        appKeys={["my_app"]}
        selectedApp="my_app"
        onAppChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    expect(getByText("app: my_app")).toBeDefined();
  });

  it("shows 'app: all' label when no app is selected", () => {
    const { getByText } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        appKeys={["my_app"]}
        selectedApp=""
        onAppChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    expect(getByText("app: all")).toBeDefined();
  });

  // -- Search input --

  it("renders search input when onSearchChange is provided", () => {
    const { getByPlaceholderText } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        search=""
        onSearchChange={vi.fn()}
        searchPlaceholder="search here..."
        testIdPrefix="test"
      />,
    );
    expect(getByPlaceholderText("search here...")).toBeDefined();
  });

  it("does not render search input when onSearchChange is not provided", () => {
    const { queryByRole } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    expect(queryByRole("textbox")).toBeNull();
  });

  it("calls onSearchChange when search input changes", () => {
    const onSearchChange = vi.fn();
    const { getByRole } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        search=""
        onSearchChange={onSearchChange}
        testIdPrefix="test"
      />,
    );
    fireEvent.input(getByRole("textbox"), { target: { value: "scheduler" } });
    expect(onSearchChange).toHaveBeenCalledWith("scheduler");
  });

  it("uses default placeholder 'Search...' when none provided", () => {
    const { getByPlaceholderText } = render(
      <TierToolbar
        tierFilter="all"
        onTierChange={vi.fn()}
        search=""
        onSearchChange={vi.fn()}
        testIdPrefix="test"
      />,
    );
    expect(getByPlaceholderText("Search...")).toBeDefined();
  });
});
