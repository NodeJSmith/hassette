import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ErrorDisplay, resolveResultDisplay } from "./error-display";

describe("resolveResultDisplay", () => {
  it("returns a timeout message for timed_out", () => {
    const result = resolveResultDisplay("timed_out", 5000);
    expect(result.label).toBe("timeout");
    expect(result.message).toBe("exceeded 5.0s budget");
  });

  it("returns a cancelled message for cancelled", () => {
    const result = resolveResultDisplay("cancelled", 250);
    expect(result.label).toBe("result");
    expect(result.message).toBe("cancelled after 250.0ms");
  });

  it("returns the error type and message for error", () => {
    const result = resolveResultDisplay("error", 100, "ValueError", "bad input");
    expect(result.label).toBe("result");
    expect(result.message).toBe("ValueError: bad input");
    expect(result.toneClass).toBe("text-destructive");
  });

  it("returns a completed message for success", () => {
    const result = resolveResultDisplay("success", 42);
    expect(result.label).toBe("result");
    expect(result.message).toBe("completed in 42.0ms");
  });

  it("returns a skipped message for skipped, not a completed-in-Xms message", () => {
    const result = resolveResultDisplay("skipped", 0);
    expect(result.label).toBe("result");
    expect(result.message).toBe("skipped");
    expect(result.message).not.toContain("completed in");
    expect(result.toneClass).toBe("text-muted-foreground");
  });
});

describe("ErrorDisplay", () => {
  it("renders the skipped message for a skipped status", () => {
    const { getByText } = render(<ErrorDisplay status="skipped" durationMs={0} />);
    expect(getByText("skipped")).not.toBeNull();
  });

  it("renders the timeout message for a timed_out status", () => {
    const { getByText } = render(<ErrorDisplay status="timed_out" durationMs={1000} />);
    expect(getByText("exceeded 1.0s budget")).not.toBeNull();
  });
});
