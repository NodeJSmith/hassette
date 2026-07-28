import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

function renderTooltip(label: string, trigger: ReactNode) {
  return render(
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>{trigger}</TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>,
  );
}

describe("Tooltip", () => {
  it("does not show the tooltip content until triggered", () => {
    renderTooltip("avg duration", <span>23ms</span>);
    expect(screen.queryByText("avg duration")).toBeNull();
  });

  it("shows the tooltip content on hover", async () => {
    const user = userEvent.setup();
    renderTooltip("avg duration", <span>23ms</span>);

    await user.hover(screen.getByText("23ms"));

    await waitFor(() => {
      expect(screen.getAllByText("avg duration").length).toBeGreaterThan(0);
    });
  });

  it("shows the tooltip content on focus", async () => {
    renderTooltip("error rate", <button type="button">3 failed</button>);

    // Radix's tooltip trigger listens for native focus events; userEvent has no standalone
    // "focus only" action (user.click would also fire pointer/mouse events), so a direct
    // DOM focus() call is the closest analog to fireEvent.focus here.
    screen.getByText("3 failed").focus();

    await waitFor(() => {
      expect(screen.getAllByText("error rate").length).toBeGreaterThan(0);
    });
  });
});
