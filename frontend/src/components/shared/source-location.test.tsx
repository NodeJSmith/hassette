import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { SourceLocation } from "./source-location";

describe("SourceLocation", () => {
  it("renders filename and line number", () => {
    const { getByTestId } = render(<SourceLocation sourceLocation="thermoscura.py:42" data-testid="src-loc" />);
    const el = getByTestId("src-loc");
    expect(el.textContent).toContain("thermoscura.py");
    expect(el.textContent).toContain("42");
  });

  it("renders filename without line number when no colon", () => {
    const { getByTestId } = render(<SourceLocation sourceLocation="thermoscura.py" data-testid="src-loc" />);
    expect(getByTestId("src-loc").textContent).toBe("thermoscura.py");
  });

  it("renders full path with line number", () => {
    const { getByTestId } = render(
      <SourceLocation sourceLocation="/apps/src/haumate/thermoscura.py:511" data-testid="src-loc" />,
    );
    const text = getByTestId("src-loc").textContent;
    expect(text).toContain("/apps/src/haumate/thermoscura.py");
    expect(text).toContain("511");
  });
});
