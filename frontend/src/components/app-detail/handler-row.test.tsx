import { describe, expect, it } from "vitest";
import { fireEvent, waitFor } from "@testing-library/preact";
import { signal } from "@preact/signals";
import { http, HttpResponse } from "msw";
import type { components } from "../../api/generated-types";
import { server } from "../../test/server";
import { renderWithAppState } from "../../test/render-helpers";
import { createListener, createInvocation } from "../../test/factories";
import { HandlerRow } from "./handler-row";

type HandlerInvocation = components["schemas"]["HandlerInvocation"];

/**
 * Render HandlerRow with sessionScope="all" so useScopedApi fires without
 * waiting for a WebSocket session ID.
 */
function renderHandlerRow(listener = createListener()) {
  return renderWithAppState(
    <HandlerRow listener={listener} />,
    { stateOverrides: { sessionScope: signal<"current" | "all">("all") } },
  );
}

describe("HandlerRow", () => {
  // -- Collapsed state --

  it("renders handler summary as title in collapsed state", () => {
    const { getByText } = renderHandlerRow(
      createListener({ handler_summary: "on_state_change()", handler_method: "my_app.on_state_change" }),
    );
    expect(getByText("on_state_change()")).toBeDefined();
  });

  it("falls back to short method name when handler_summary is null", () => {
    const { getByText } = renderHandlerRow(
      createListener({ handler_summary: null as unknown as string, handler_method: "my_app.on_light_change" }),
    );
    expect(getByText("on_light_change")).toBeDefined();
  });

  it("renders total invocation count in collapsed state", () => {
    const { getByText } = renderHandlerRow(
      createListener({ total_invocations: 5 }),
    );
    expect(getByText("5 calls")).toBeDefined();
  });

  it("shows failed count with danger styling when failed > 0", () => {
    const { getByText } = renderHandlerRow(
      createListener({ failed: 3, total_invocations: 10 }),
    );
    expect(getByText("3 failed")).toBeDefined();
  });

  it("does not show failed count when failed is 0", () => {
    const { queryByText } = renderHandlerRow(
      createListener({ failed: 0, total_invocations: 5 }),
    );
    expect(queryByText(/failed/)).toBeNull();
  });

  it("renders danger dot class when failed > 0", () => {
    const { container } = renderHandlerRow(
      createListener({ failed: 2, total_invocations: 5 }),
    );
    const dot = container.querySelector(".ht-item-row__dot--danger");
    expect(dot).not.toBeNull();
  });

  it("renders success dot class when total_invocations > 0 and failed is 0", () => {
    const { container } = renderHandlerRow(
      createListener({ total_invocations: 5, failed: 0 }),
    );
    const dot = container.querySelector(".ht-item-row__dot--success");
    expect(dot).not.toBeNull();
  });

  it("renders neutral dot class when total_invocations is 0 and failed is 0", () => {
    const { container } = renderHandlerRow(
      createListener({ total_invocations: 0, failed: 0 }),
    );
    const dot = container.querySelector(".ht-item-row__dot--neutral");
    expect(dot).not.toBeNull();
  });

  it("row is not expanded on initial render", () => {
    const { container } = renderHandlerRow();
    const row = container.querySelector(".ht-item-row");
    expect(row?.classList.contains("is-expanded")).toBe(false);
  });

  // -- Expand toggle --

  it("expands row when toggle button is clicked", () => {
    const { container } = renderHandlerRow();
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(button);
    const row = container.querySelector(".ht-item-row");
    expect(row?.classList.contains("is-expanded")).toBe(true);
  });

  it("collapses row when expanded toggle is clicked again", () => {
    const { container } = renderHandlerRow();
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(button); // expand
    fireEvent.click(button); // collapse
    const row = container.querySelector(".ht-item-row");
    expect(row?.classList.contains("is-expanded")).toBe(false);
  });

  it("keyboard Enter key toggles expansion", () => {
    const { container } = renderHandlerRow();
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.keyDown(button, { key: "Enter" });
    const row = container.querySelector(".ht-item-row");
    expect(row?.classList.contains("is-expanded")).toBe(true);
  });

  it("keyboard Space key toggles expansion", () => {
    const { container } = renderHandlerRow();
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.keyDown(button, { key: " " });
    const row = container.querySelector(".ht-item-row");
    expect(row?.classList.contains("is-expanded")).toBe(true);
  });

  // -- Expanded state with MSW --

  it("shows loading state immediately after expansion", () => {
    server.use(
      http.get("/api/telemetry/handler/:listener_id/invocations", async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return HttpResponse.json([]);
      }),
    );

    const { container } = renderHandlerRow(createListener({ listener_id: 1 }));
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(button);
    expect(container.textContent).toContain("Loading invocations...");
  });

  it("fetches and renders invocation table after expansion", async () => {
    const invocations = [createInvocation({ status: "success" })];
    server.use(
      http.get("/api/telemetry/handler/:listener_id/invocations", () => {
        return HttpResponse.json<HandlerInvocation[]>(invocations);
      }),
    );

    const { container } = renderHandlerRow(createListener({ listener_id: 7 }));
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(button);

    await waitFor(() => {
      expect(container.querySelector("[data-testid='invocation-table-7']")).not.toBeNull();
    });
  });

  it("renders invocation status badge after expansion", async () => {
    const invocations = [createInvocation({ status: "success" })];
    server.use(
      http.get("/api/telemetry/handler/:listener_id/invocations", () => {
        return HttpResponse.json<HandlerInvocation[]>(invocations);
      }),
    );

    const { container } = renderHandlerRow(createListener({ listener_id: 5 }));
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(button);

    await waitFor(() => {
      const badge = container.querySelector(".ht-badge--success");
      expect(badge).not.toBeNull();
    });
  });

  it("shows 'No invocations recorded' when API returns empty list", async () => {
    server.use(
      http.get("/api/telemetry/handler/:listener_id/invocations", () => {
        return HttpResponse.json<HandlerInvocation[]>([]);
      }),
    );

    const { container } = renderHandlerRow(createListener({ listener_id: 3 }));
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(button);

    await waitFor(() => {
      expect(container.textContent).toContain("No invocations recorded.");
    });
  });

  // -- Optional metadata in expanded detail --

  it("renders entity_id tag when entity_id is set", async () => {
    server.use(
      http.get("/api/telemetry/handler/:listener_id/invocations", () => {
        return HttpResponse.json<HandlerInvocation[]>([]);
      }),
    );

    const { container } = renderHandlerRow(
      createListener({ entity_id: "light.kitchen", listener_id: 10 }),
    );
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(button);

    await waitFor(() => {
      expect(container.querySelector("[data-testid='listener-options']")).not.toBeNull();
    });

    expect(container.textContent).toContain("light.kitchen");
  });

  it("does not render listener-options when no optional attributes are set", async () => {
    server.use(
      http.get("/api/telemetry/handler/:listener_id/invocations", () => {
        return HttpResponse.json<HandlerInvocation[]>([]);
      }),
    );

    const { container } = renderHandlerRow(
      createListener({
        entity_id: null,
        immediate: 0,
        duration: null,
        once: 0,
        debounce: null,
        throttle: null,
        listener_id: 11,
      }),
    );
    const button = container.querySelector("[role='button']") as HTMLElement;
    fireEvent.click(button);

    await waitFor(() => {
      expect(container.textContent).toContain("No invocations recorded.");
    });
    expect(container.querySelector("[data-testid='listener-options']")).toBeNull();
  });
});
