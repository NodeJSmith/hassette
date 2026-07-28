import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "@/components/ui/badge";

describe("Badge", () => {
  describe("status variants (formerly Badge's BadgeVariant)", () => {
    it("applies success variant", () => {
      const { getByTestId } = render(
        <Badge variant="success" data-testid="b">
          ok
        </Badge>,
      );
      expect(getByTestId("b").getAttribute("data-variant")).toBe("success");
    });

    it("applies danger variant", () => {
      const { getByTestId } = render(
        <Badge variant="danger" data-testid="b">
          err
        </Badge>,
      );
      expect(getByTestId("b").getAttribute("data-variant")).toBe("danger");
    });

    it("applies warning variant", () => {
      const { getByTestId } = render(
        <Badge variant="warning" data-testid="b">
          warn
        </Badge>,
      );
      expect(getByTestId("b").getAttribute("data-variant")).toBe("warning");
    });

    it("applies info variant", () => {
      const { getByTestId } = render(
        <Badge variant="info" data-testid="b">
          info
        </Badge>,
      );
      expect(getByTestId("b").getAttribute("data-variant")).toBe("info");
    });

    it("applies neutral variant", () => {
      const { getByTestId } = render(
        <Badge variant="neutral" data-testid="b">
          n/a
        </Badge>,
      );
      expect(getByTestId("b").getAttribute("data-variant")).toBe("neutral");
    });
  });

  describe("chip-style variants (formerly Chip's ChipVariant, flattened)", () => {
    it("applies job variant", () => {
      const { getByTestId } = render(
        <Badge variant="job" data-testid="c">
          sched
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("job");
    });

    it("applies listener variant", () => {
      const { getByTestId } = render(
        <Badge variant="listener" data-testid="c">
          mod
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("listener");
    });

    it("applies origin variant", () => {
      const { getByTestId } = render(
        <Badge variant="origin" data-testid="c">
          origin
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("origin");
    });

    it("applies muted variant", () => {
      const { getByTestId } = render(
        <Badge variant="muted" data-testid="c">
          muted
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("muted");
    });
  });

  describe("kind sub-variants (formerly Chip's variant='kind' kind={ChipKind} union)", () => {
    it("applies kind-ok variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-ok" data-testid="c">
          ok
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("kind-ok");
    });

    it("applies kind-warn variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-warn" data-testid="c">
          warn
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("kind-warn");
    });

    it("applies kind-err variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-err" data-testid="c">
          err
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("kind-err");
    });

    it("applies kind-cancel variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-cancel" data-testid="c">
          cancel
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("kind-cancel");
    });

    it("applies kind-mute variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-mute" data-testid="c">
          mute
        </Badge>,
      );
      expect(getByTestId("c").getAttribute("data-variant")).toBe("kind-mute");
    });
  });

  describe("size prop", () => {
    it("applies xs size", () => {
      const { getByTestId } = render(
        <Badge variant="success" size="xs" data-testid="b">
          ok
        </Badge>,
      );
      expect(getByTestId("b").className).toMatch(/text-\[11px\]/);
    });

    it("applies sm size", () => {
      const { getByTestId } = render(
        <Badge variant="success" size="sm" data-testid="b">
          ok
        </Badge>,
      );
      expect(getByTestId("b").className).toMatch(/text-xs/);
    });

    it("applies md size", () => {
      const { getByTestId } = render(
        <Badge variant="success" size="md" data-testid="b">
          ok
        </Badge>,
      );
      expect(getByTestId("b").className).toMatch(/text-sm/);
    });
  });

  describe("class prop", () => {
    it("merges additional class into span className", () => {
      const { getByTestId } = render(
        <Badge variant="success" className="my-extra-class" data-testid="b">
          ok
        </Badge>,
      );
      expect(getByTestId("b").className).toMatch(/my-extra-class/);
    });
  });

  describe("children", () => {
    it("renders text children", () => {
      const { getByTestId } = render(
        <Badge variant="success" data-testid="b">
          running
        </Badge>,
      );
      expect(getByTestId("b").textContent).toBe("running");
    });

    it("renders mixed children (text + icon element)", () => {
      const { getByTestId } = render(
        <Badge variant="kind-ok" data-testid="b">
          <svg data-testid="icon" />
          running
        </Badge>,
      );
      const el = getByTestId("b");
      expect(el.querySelector("[data-testid='icon']")).not.toBeNull();
      expect(el.textContent).toContain("running");
    });
  });

  describe("pass-through attributes", () => {
    it("passes data-testid through to span element", () => {
      const { getByTestId } = render(
        <Badge variant="success" data-testid="my-badge">
          ok
        </Badge>,
      );
      expect(getByTestId("my-badge")).not.toBeNull();
    });

    it("passes aria-label through to span element", () => {
      const { getByLabelText } = render(
        <Badge variant="success" aria-label="status: running">
          ok
        </Badge>,
      );
      expect(getByLabelText("status: running")).not.toBeNull();
    });
  });

  describe("renders as span", () => {
    it("renders a <span> element", () => {
      const { getByTestId } = render(
        <Badge variant="neutral" data-testid="b">
          text
        </Badge>,
      );
      expect(getByTestId("b").tagName.toLowerCase()).toBe("span");
    });
  });
});
