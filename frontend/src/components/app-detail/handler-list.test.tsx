import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/preact";
import { HandlerList } from "./handler-list";
import { createListener } from "../../test/factories";

// Mock HandlerRow to isolate HandlerList behavior — HandlerRow calls useScopedApi
// which requires AppStateContext and MSW. HandlerList's behavior is purely about
// rendering the right number of rows and handling edge-case inputs.
vi.mock("./handler-row", () => ({
  HandlerRow: ({ listener }: { listener: { listener_id: number; handler_summary: string | null; handler_method: string } }) => (
    <div data-testid={`handler-row-${listener.listener_id}`}>
      {listener.handler_summary ?? listener.handler_method}
    </div>
  ),
}));

describe("HandlerList", () => {
  it("renders nothing when listeners is null", () => {
    const { container } = render(<HandlerList listeners={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when listeners is an empty array", () => {
    const { container } = render(<HandlerList listeners={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders handler-list container with testid", () => {
    const listeners = [createListener({ listener_id: 1 })];
    const { getByTestId } = render(<HandlerList listeners={listeners} />);
    expect(getByTestId("handler-list")).toBeDefined();
  });

  it("renders a HandlerRow for each listener", () => {
    const listeners = [
      createListener({ listener_id: 1 }),
      createListener({ listener_id: 2 }),
      createListener({ listener_id: 3 }),
    ];
    const { getByTestId } = render(<HandlerList listeners={listeners} />);
    expect(getByTestId("handler-row-1")).toBeDefined();
    expect(getByTestId("handler-row-2")).toBeDefined();
    expect(getByTestId("handler-row-3")).toBeDefined();
  });

  it("renders exactly as many rows as listeners", () => {
    const listeners = [
      createListener({ listener_id: 10 }),
      createListener({ listener_id: 20 }),
    ];
    const { container } = render(<HandlerList listeners={listeners} />);
    const rows = container.querySelectorAll("[data-testid^='handler-row-']");
    expect(rows.length).toBe(2);
  });

  it("renders handler summary text via mocked HandlerRow", () => {
    const listeners = [
      createListener({ listener_id: 5, handler_summary: "on_motion_detected()" }),
    ];
    const { getByText } = render(<HandlerList listeners={listeners} />);
    expect(getByText("on_motion_detected()")).toBeDefined();
  });
});
