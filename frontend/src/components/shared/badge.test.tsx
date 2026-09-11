import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "@/components/ui/badge";

const BADGE_TEST_ID = "badge";
const PASSTHROUGH_TEST_ID = "my-badge";

describe("Badge", () => {
  describe("status variants (formerly Badge's BadgeVariant)", () => {
    it("applies success variant", () => {
      const { getByTestId } = render(
        <Badge variant="success" data-testid={BADGE_TEST_ID}>
          ok
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("success");
    });

    it("applies danger variant", () => {
      const { getByTestId } = render(
        <Badge variant="danger" data-testid={BADGE_TEST_ID}>
          err
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("danger");
    });

    it("applies warning variant", () => {
      const { getByTestId } = render(
        <Badge variant="warning" data-testid={BADGE_TEST_ID}>
          warn
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("warning");
    });

    it("applies info variant", () => {
      const { getByTestId } = render(
        <Badge variant="info" data-testid={BADGE_TEST_ID}>
          info
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("info");
    });

    it("applies neutral variant", () => {
      const { getByTestId } = render(
        <Badge variant="neutral" data-testid={BADGE_TEST_ID}>
          n/a
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("neutral");
    });
  });

  describe("chip-style variants (formerly Chip's ChipVariant, flattened)", () => {
    it("applies job variant", () => {
      const { getByTestId } = render(
        <Badge variant="job" data-testid={BADGE_TEST_ID}>
          sched
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("job");
    });

    it("applies listener variant", () => {
      const { getByTestId } = render(
        <Badge variant="listener" data-testid={BADGE_TEST_ID}>
          mod
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("listener");
    });

    it("applies origin variant", () => {
      const { getByTestId } = render(
        <Badge variant="origin" data-testid={BADGE_TEST_ID}>
          origin
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("origin");
    });

    it("applies muted variant", () => {
      const { getByTestId } = render(
        <Badge variant="muted" data-testid={BADGE_TEST_ID}>
          muted
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("muted");
    });
  });

  describe("kind sub-variants (formerly Chip's variant='kind' kind={ChipKind} union)", () => {
    it("applies kind-ok variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-ok" data-testid={BADGE_TEST_ID}>
          ok
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("kind-ok");
    });

    it("applies kind-warn variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-warn" data-testid={BADGE_TEST_ID}>
          warn
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("kind-warn");
    });

    it("applies kind-err variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-err" data-testid={BADGE_TEST_ID}>
          err
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("kind-err");
    });

    it("applies kind-cancel variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-cancel" data-testid={BADGE_TEST_ID}>
          cancel
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("kind-cancel");
    });

    it("applies kind-mute variant", () => {
      const { getByTestId } = render(
        <Badge variant="kind-mute" data-testid={BADGE_TEST_ID}>
          mute
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).getAttribute("data-variant")).toBe("kind-mute");
    });
  });

  describe("size prop", () => {
    it("applies xs size", () => {
      const { getByTestId } = render(
        <Badge variant="success" size="xs" data-testid={BADGE_TEST_ID}>
          ok
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).className).toMatch(/text-\[11px\]/);
    });

    it("applies sm size", () => {
      const { getByTestId } = render(
        <Badge variant="success" size="sm" data-testid={BADGE_TEST_ID}>
          ok
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).className).toMatch(/text-xs/);
    });

    it("applies md size", () => {
      const { getByTestId } = render(
        <Badge variant="success" size="md" data-testid={BADGE_TEST_ID}>
          ok
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).className).toMatch(/text-sm/);
    });
  });

  describe("class prop", () => {
    it("merges additional class into span className", () => {
      const { getByTestId } = render(
        <Badge variant="success" className="my-extra-class" data-testid={BADGE_TEST_ID}>
          ok
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).className).toMatch(/my-extra-class/);
    });
  });

  describe("children", () => {
    it("renders text children", () => {
      const { getByTestId } = render(
        <Badge variant="success" data-testid={BADGE_TEST_ID}>
          running
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).textContent).toBe("running");
    });

    it("renders mixed children (text + icon element)", () => {
      const { getByTestId } = render(
        <Badge variant="kind-ok" data-testid={BADGE_TEST_ID}>
          <svg data-testid="icon" />
          running
        </Badge>,
      );
      const el = getByTestId(BADGE_TEST_ID);
      expect(el.querySelector("[data-testid='icon']")).not.toBeNull();
      expect(el.textContent).toContain("running");
    });
  });

  describe("pass-through attributes", () => {
    // Needs an id no other test in this file renders, so the assertion can only pass
    // if an arbitrary caller-supplied id actually reached the DOM.
    it("passes data-testid through to span element", () => {
      const { getByTestId } = render(
        <Badge variant="success" data-testid={PASSTHROUGH_TEST_ID}>
          ok
        </Badge>,
      );
      expect(getByTestId(PASSTHROUGH_TEST_ID)).not.toBeNull();
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
        <Badge variant="neutral" data-testid={BADGE_TEST_ID}>
          text
        </Badge>,
      );
      expect(getByTestId(BADGE_TEST_ID).tagName.toLowerCase()).toBe("span");
    });
  });
});
