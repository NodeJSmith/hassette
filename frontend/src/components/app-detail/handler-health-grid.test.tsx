import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { createJob, createListener } from "../../test/factories";
import { createWouterMock } from "../../test/mock-wouter";
import { renderWithAppState } from "../../test/render-helpers";
import { HandlerHealthGrid } from "./handler-health-grid";
import { buildItems } from "./handler-list";
import type { UnifiedItem } from "./unified-handler-row";

vi.mock("wouter", () =>
  createWouterMock({
    useLocation: () => ["/", vi.fn()],
    useSearch: () => "",
  }),
);

const CARD_TESTID_PREFIX = "overview-health-card-";
const CARD_SELECTOR = `[data-testid^='${CARD_TESTID_PREFIX}']`;
const DEFAULT_GRID_PROPS = { appKey: "test_app", instanceQs: "" };

function cardTestId(kind: UnifiedItem["kind"], id: number) {
  return `${CARD_TESTID_PREFIX}${kind}-${id}`;
}

function renderGrid(items: UnifiedItem[], overrides: Partial<typeof DEFAULT_GRID_PROPS> = {}) {
  return render(<HandlerHealthGrid items={items} {...DEFAULT_GRID_PROPS} {...overrides} />);
}

function renderGridWithAppState(items: UnifiedItem[], overrides: Partial<typeof DEFAULT_GRID_PROPS> = {}) {
  return renderWithAppState(<HandlerHealthGrid items={items} {...DEFAULT_GRID_PROPS} {...overrides} />);
}

function makeListenerItem(overrides: Parameters<typeof createListener>[0] = {}) {
  const listener = createListener({ listener_id: 1, total_invocations: 1, ...overrides });
  return buildItems([listener], [])[0];
}

function makeJobItem(overrides: Parameters<typeof createJob>[0] = {}) {
  const job = createJob({ job_id: 1, total_executions: 1, ...overrides });
  return buildItems([], [job])[0];
}

describe("HandlerHealthGrid — empty state", () => {
  it("renders the section wrapper with testid even when empty", () => {
    const { getByTestId } = renderGrid([]);
    expect(getByTestId("overview-health-grid")).toBeDefined();
  });

  it("renders EmptyState with testid when no items", () => {
    const { getByTestId } = renderGrid([]);
    expect(getByTestId("overview-health-empty")).toBeDefined();
  });

  it("does not render cards when items are empty", () => {
    const { container } = renderGrid([]);
    expect(container.querySelectorAll(CARD_SELECTOR)).toHaveLength(0);
  });
});

describe("HandlerHealthGrid — with items", () => {
  it("renders a card per item", () => {
    const items = [makeListenerItem({ listener_id: 1 }), makeJobItem({ job_id: 2 })];
    const { getByTestId } = renderGridWithAppState(items);
    expect(getByTestId(cardTestId("listener", 1))).toBeDefined();
    expect(getByTestId(cardTestId("job", 2))).toBeDefined();
  });

  it("does not render EmptyState when items are present", () => {
    const items = [makeListenerItem({ listener_id: 1 })];
    const { queryByTestId } = renderGridWithAppState(items);
    expect(queryByTestId("overview-health-empty")).toBeNull();
  });

  it("renders the section heading", () => {
    const items = [makeListenerItem({ listener_id: 1 })];
    const { container } = renderGridWithAppState(items);
    const heading = container.querySelector("h3");
    expect(heading?.textContent?.toLowerCase()).toContain("handler health");
  });
});

describe("HandlerHealthGrid — sorting (failing first)", () => {
  it("renders failing items before healthy items", () => {
    const items = [
      makeListenerItem({ listener_id: 1, failed: 0, timed_out: 0, handler_summary: "on_healthy()" }),
      makeListenerItem({ listener_id: 2, failed: 2, total_invocations: 5, handler_summary: "on_broken()" }),
    ];
    const { container } = renderGridWithAppState(items);
    const cards = container.querySelectorAll(CARD_SELECTOR);
    expect(cards[0].getAttribute("data-testid")).toBe(cardTestId("listener", 2));
    expect(cards[1].getAttribute("data-testid")).toBe(cardTestId("listener", 1));
  });
});

describe("HandlerHealthGrid — passes props to cards", () => {
  it("renders correct number of cards for given items", () => {
    const items = [
      makeListenerItem({ listener_id: 3 }),
      makeJobItem({ job_id: 7 }),
      makeListenerItem({ listener_id: 5 }),
    ];
    const { container } = renderGridWithAppState(items, { instanceQs: "?instance=1" });
    const cards = container.querySelectorAll(CARD_SELECTOR);
    expect(cards).toHaveLength(3);
  });
});
