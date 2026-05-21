import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import { Chip } from "./chip";

describe("Chip", () => {
  describe("renders as span", () => {
    it("renders a <span> element", () => {
      const { getByTestId } = render(
        <Chip variant="modifier" data-testid="c">
          text
        </Chip>,
      );
      expect(getByTestId("c").tagName.toLowerCase()).toBe("span");
    });
  });

  describe("variant prop", () => {
    it("applies modifier class when variant='modifier'", () => {
      const { getByTestId } = render(
        <Chip variant="modifier" data-testid="c">
          mod
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/modifier/);
    });

    it("applies schedule class when variant='schedule'", () => {
      const { getByTestId } = render(
        <Chip variant="schedule" data-testid="c">
          sched
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/schedule/);
    });

    it("applies kind base class when variant='kind'", () => {
      const { getByTestId } = render(
        <Chip variant="kind" kind="ok" data-testid="c">
          ok
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/kind/);
    });

    it("applies origin class when variant='origin'", () => {
      const { getByTestId } = render(
        <Chip variant="origin" data-testid="c">
          origin
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/origin/);
    });

    it("applies muted class when variant='muted'", () => {
      const { getByTestId } = render(
        <Chip variant="muted" data-testid="c">
          muted
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/muted/);
    });
  });

  describe("kind prop (when variant='kind')", () => {
    it("applies kindOk class when kind='ok'", () => {
      const { getByTestId } = render(
        <Chip variant="kind" kind="ok" data-testid="c">
          ok
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/kindOk/);
    });

    it("applies kindWarn class when kind='warn'", () => {
      const { getByTestId } = render(
        <Chip variant="kind" kind="warn" data-testid="c">
          warn
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/kindWarn/);
    });

    it("applies kindErr class when kind='err'", () => {
      const { getByTestId } = render(
        <Chip variant="kind" kind="err" data-testid="c">
          err
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/kindErr/);
    });

    it("applies kindMute class when kind='mute'", () => {
      const { getByTestId } = render(
        <Chip variant="kind" kind="mute" data-testid="c">
          mute
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/kindMute/);
    });

    it("does NOT auto-render StatusShape — callers pass children", () => {
      const { getByTestId } = render(
        <Chip variant="kind" kind="ok" data-testid="c">
          ok label
        </Chip>,
      );
      // No SVG rendered unless caller passes one as child
      expect(getByTestId("c").querySelector("svg")).toBeNull();
    });
  });

  describe("data-variant attribute", () => {
    it("emits data-variant='modifier' on the root span", () => {
      const { getByTestId } = render(
        <Chip variant="modifier" data-testid="c">
          mod
        </Chip>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("modifier");
    });

    it("emits data-variant='muted' on the root span", () => {
      const { getByTestId } = render(
        <Chip variant="muted" data-testid="c">
          muted
        </Chip>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("muted");
    });

    it("emits data-variant='kind' on the root span", () => {
      const { getByTestId } = render(
        <Chip variant="kind" kind="ok" data-testid="c">
          ok
        </Chip>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("kind");
    });

    it("emits data-variant='schedule' on the root span", () => {
      const { getByTestId } = render(
        <Chip variant="schedule" data-testid="c">
          sched
        </Chip>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("schedule");
    });

    it("emits data-variant='origin' on the root span", () => {
      const { getByTestId } = render(
        <Chip variant="origin" data-testid="c">
          origin
        </Chip>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("origin");
    });
  });

  describe("size prop", () => {
    it("applies no size class when size is 'default'", () => {
      const { getByTestId } = render(
        <Chip variant="modifier" size="default" data-testid="c">
          mod
        </Chip>,
      );
      expect(getByTestId("c").className).not.toMatch(/\bsm\b/);
    });

    it("applies sm class when size='sm'", () => {
      const { getByTestId } = render(
        <Chip variant="modifier" size="sm" data-testid="c">
          mod
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/sm/);
    });
  });

  describe("class prop", () => {
    it("merges additional class into span className", () => {
      const { getByTestId } = render(
        <Chip variant="muted" class="extra-class" data-testid="c">
          text
        </Chip>,
      );
      expect(getByTestId("c").className).toMatch(/extra-class/);
    });
  });

  describe("aria-label pass-through", () => {
    it("passes aria-label through to the root span", () => {
      const { getByLabelText } = render(
        <Chip variant="origin" aria-label="origin: event">
          EVENT
        </Chip>,
      );
      expect(getByLabelText("origin: event")).not.toBeNull();
    });
  });

  describe("children", () => {
    it("renders text children", () => {
      const { getByTestId } = render(
        <Chip variant="modifier" data-testid="c">
          hello
        </Chip>,
      );
      expect(getByTestId("c").textContent).toBe("hello");
    });

    it("renders element children (e.g. StatusShape passed by caller)", () => {
      const { getByTestId } = render(
        <Chip variant="kind" kind="ok" data-testid="c">
          <svg data-testid="icon" />
          label
        </Chip>,
      );
      expect(getByTestId("c").querySelector("[data-testid='icon']")).not.toBeNull();
      expect(getByTestId("c").textContent).toContain("label");
    });
  });

  describe("no duplicate auto variant", () => {
    it("does not have an auto class (merged into muted)", () => {
      // Variant 'auto' does not exist — only 'muted' covers both use cases.
      // This documents FR#16: duplicate --auto/--muted variants are consolidated.
      const { getByTestId } = render(
        <Chip variant="muted" data-testid="c">
          text
        </Chip>,
      );
      expect(getByTestId("c").className).not.toMatch(/\bauto\b/);
    });
  });
});
