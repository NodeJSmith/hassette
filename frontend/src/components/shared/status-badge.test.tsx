import { describe, expect, it } from "vitest";
import { render } from "@testing-library/preact";
import { StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  describe("default size (full badge)", () => {
    it("renders running status with success variant", () => {
      const { container } = render(<StatusBadge status="running" />);
      const badge = container.querySelector(".ht-status-badge");
      expect(badge).not.toBeNull();
      expect(badge!.className).toContain("ht-status-badge--success");
    });

    it("renders failed status with danger variant", () => {
      const { container } = render(<StatusBadge status="failed" />);
      const badge = container.querySelector(".ht-status-badge");
      expect(badge!.className).toContain("ht-status-badge--danger");
    });

    it("renders stopped status with warning variant", () => {
      const { container } = render(<StatusBadge status="stopped" />);
      const badge = container.querySelector(".ht-status-badge");
      expect(badge!.className).toContain("ht-status-badge--warning");
    });

    it("renders disabled status with neutral variant", () => {
      const { container } = render(<StatusBadge status="disabled" />);
      const badge = container.querySelector(".ht-status-badge");
      expect(badge!.className).toContain("ht-status-badge--neutral");
    });

    it("renders blocked status with warning variant", () => {
      const { container } = render(<StatusBadge status="blocked" />);
      const badge = container.querySelector(".ht-status-badge");
      expect(badge!.className).toContain("ht-status-badge--warning");
    });

    it("renders the status text in label span", () => {
      const { container } = render(<StatusBadge status="stopped" />);
      const label = container.querySelector(".ht-status-badge__label");
      expect(label?.textContent).toBe("stopped");
    });

    it("renders a dot element", () => {
      const { container } = render(<StatusBadge status="running" />);
      const dot = container.querySelector(".ht-status-badge__dot");
      expect(dot).not.toBeNull();
    });

    it("sets title when blockReason is provided", () => {
      const { container } = render(<StatusBadge status="blocked" blockReason="missing dependency" />);
      const badge = container.querySelector(".ht-status-badge");
      expect(badge?.getAttribute("title")).toBe("missing dependency");
    });

    it("does not set title when blockReason is absent", () => {
      const { container } = render(<StatusBadge status="running" />);
      const badge = container.querySelector(".ht-status-badge");
      // title may be undefined or empty string without blockReason
      const title = badge?.getAttribute("title");
      expect(!title || title === "").toBe(true);
    });
  });

  describe("small size", () => {
    it("renders small badge for running status", () => {
      const { container } = render(<StatusBadge status="running" size="small" />);
      const badge = container.querySelector(".ht-badge--sm");
      expect(badge).not.toBeNull();
      expect(badge!.className).toContain("ht-badge--success");
    });

    it("renders small badge for failed status with danger variant", () => {
      const { container } = render(<StatusBadge status="failed" size="small" />);
      const badge = container.querySelector(".ht-badge--sm");
      expect(badge!.className).toContain("ht-badge--danger");
    });

    it("renders small badge for stopped status with warning variant", () => {
      const { container } = render(<StatusBadge status="stopped" size="small" />);
      const badge = container.querySelector(".ht-badge--sm");
      expect(badge!.className).toContain("ht-badge--warning");
    });

    it("renders small badge for disabled status with neutral variant", () => {
      const { container } = render(<StatusBadge status="disabled" size="small" />);
      const badge = container.querySelector(".ht-badge--sm");
      expect(badge!.className).toContain("ht-badge--neutral");
    });

    it("renders small badge for blocked status with warning variant", () => {
      const { container } = render(<StatusBadge status="blocked" size="small" />);
      const badge = container.querySelector(".ht-badge--sm");
      expect(badge!.className).toContain("ht-badge--warning");
    });

    it("shows status text directly in small badge", () => {
      const { container } = render(<StatusBadge status="stopped" size="small" />);
      const badge = container.querySelector(".ht-badge--sm");
      expect(badge?.textContent).toBe("stopped");
    });

    it("sets title on small badge when blockReason is provided", () => {
      const { container } = render(
        <StatusBadge status="blocked" size="small" blockReason="waiting for dep" />,
      );
      const badge = container.querySelector(".ht-badge--sm");
      expect(badge?.getAttribute("title")).toBe("waiting for dep");
    });

    it("does not render status-badge dot in small mode", () => {
      const { container } = render(<StatusBadge status="running" size="small" />);
      expect(container.querySelector(".ht-status-badge__dot")).toBeNull();
    });
  });

  describe("unknown status fallback", () => {
    it("renders neutral variant for unknown status", () => {
      const { container } = render(<StatusBadge status="unknown_status" />);
      const badge = container.querySelector(".ht-status-badge");
      expect(badge!.className).toContain("ht-status-badge--neutral");
    });
  });
});
