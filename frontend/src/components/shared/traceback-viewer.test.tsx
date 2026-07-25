import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { TracebackViewer } from "./traceback-viewer";

const TRACEBACK = [
  "Traceback (most recent call last):",
  '  File "/app/examples/demo_stimulator.py", line 42, in sensor_health_check',
  "    value = float(state.state)",
  "TypeError: float() argument must be a string or a real number, not 'NoneType'",
].join("\n");

describe("TracebackViewer", () => {
  it("splits the final exception line out of the frames", () => {
    const { getByTestId, container } = render(<TracebackViewer traceback={TRACEBACK} testIdPrefix="t" />);
    expect(container.textContent).toContain("TypeError: float() argument");
    expect(getByTestId("t-traceback").textContent).not.toContain("TypeError: float() argument");
  });

  it("colours the path, line number and function of a frame line separately", () => {
    const { getByTestId } = render(<TracebackViewer traceback={TRACEBACK} testIdPrefix="t" />);
    const frames = getByTestId("t-traceback");

    const path = frames.querySelector('[class*="path"]');
    const lineNo = frames.querySelector('[class*="lineNo"]');
    const func = frames.querySelector('[class*="func"]');

    expect(path?.textContent).toBe('"/app/examples/demo_stimulator.py"');
    expect(lineNo?.textContent).toBe("42");
    expect(func?.textContent).toBe("sensor_health_check");
  });

  it("leaves the echoed source line uncoloured by frame tokens", () => {
    const { getByTestId } = render(<TracebackViewer traceback={TRACEBACK} testIdPrefix="t" />);
    const frames = getByTestId("t-traceback");
    expect(frames.textContent).toContain("value = float(state.state)");
    // Only the one frame line should produce path/lineNo/func spans.
    expect(frames.querySelectorAll('[class*="lineNo"]')).toHaveLength(1);
  });

  it("renders exception text as text, never as markup", () => {
    const hostile = ['  File "/app/x.py", line 1, in f', "    pass", "ValueError: <img src=x onerror=alert(1)>"].join(
      "\n",
    );
    const { container } = render(<TracebackViewer traceback={hostile} testIdPrefix="t" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
  });

  it("falls back to a plain block when there is no frame to split", () => {
    const { getByTestId } = render(<TracebackViewer traceback="single line" testIdPrefix="t" />);
    expect(getByTestId("t-traceback").textContent).toBe("single line");
  });
});
