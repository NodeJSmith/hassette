import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { RegistrationSource } from "./registration-source";

describe("RegistrationSource", () => {
  it("renders the label and code snippet", () => {
    const { getByTestId } = render(
      <RegistrationSource
        source="self.bus.on_state_change('light.kitchen', handler=self.on_light)"
        data-testid="reg-src"
      />,
    );
    const el = getByTestId("reg-src");
    expect(el.textContent).toContain("Registration");
    expect(el.textContent).toContain("on_state_change");
  });

  it("preserves multiline source formatting", () => {
    const source = `self.scheduler.run_every(
    self._on_tick,
    seconds=300,
)`;
    const { getByTestId } = render(<RegistrationSource source={source} data-testid="reg-src" />);
    const code = getByTestId("reg-src").querySelector("code");
    expect(code?.textContent).toContain("seconds=300");
  });
});
