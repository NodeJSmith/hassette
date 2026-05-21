import { fireEvent, render } from "@testing-library/preact";
import { describe, expect, it, vi } from "vitest";

import { ColumnPicker } from "./column-picker";
import { COLUMNS, REQUIRED_COLUMNS } from "./constants";
import type { ColumnId } from "./types";

// ColumnFilterPopover uses @floating-ui/dom which cannot compute positions in
// jsdom. We stub it to a simple pass-through so tests focus on ColumnPicker
// behaviour rather than floating-ui internals.
vi.mock("../column-filter-popover/index", () => ({
  ColumnFilterPopover: ({ open, children }: { open: boolean; children: unknown }) =>
    open ? <div role="dialog">{children as never}</div> : null,
}));

function renderPicker(overrides: Partial<Parameters<typeof ColumnPicker>[0]> = {}) {
  const defaults = {
    selectedColumns: ["level", "timestamp", "app", "message"] as ColumnId[],
    viewportHidden: new Set<ColumnId>(),
    onToggle: vi.fn(),
    onReset: vi.fn(),
  };
  return { ...render(<ColumnPicker {...defaults} {...overrides} />), defaults };
}

describe("ColumnPicker", () => {
  describe("trigger button", () => {
    it("renders trigger button with aria-label 'Choose visible columns'", () => {
      const { getByLabelText } = renderPicker();
      expect(getByLabelText("Choose visible columns")).not.toBeNull();
    });

    it("renders trigger button with data-testid 'column-picker'", () => {
      const { getByTestId } = renderPicker();
      expect(getByTestId("column-picker")).not.toBeNull();
    });

    it("popover is closed on initial render (no checkboxes visible)", () => {
      const { queryByRole } = renderPicker();
      expect(queryByRole("dialog")).toBeNull();
    });
  });

  describe("opening the popover", () => {
    it("clicking the trigger opens the popover", () => {
      const { getByTestId, queryByRole } = renderPicker();
      fireEvent.click(getByTestId("column-picker"));
      expect(queryByRole("dialog")).not.toBeNull();
    });

    it("shows a checkbox for each column defined in COLUMNS", () => {
      const { getByTestId, getAllByRole } = renderPicker();
      fireEvent.click(getByTestId("column-picker"));
      const checkboxes = getAllByRole("checkbox");
      expect(checkboxes).toHaveLength(COLUMNS.length);
    });
  });

  describe("checkbox checked state", () => {
    it("selected columns have checked checkboxes", () => {
      const selectedColumns: ColumnId[] = ["level", "app", "message"];
      const { getByTestId, getAllByRole } = renderPicker({ selectedColumns });
      fireEvent.click(getByTestId("column-picker"));

      const checkboxes = getAllByRole("checkbox") as HTMLInputElement[];
      const checkedLabels = checkboxes.filter((cb) => cb.checked).map((cb) => cb.closest("label")?.textContent?.trim());

      for (const col of COLUMNS.filter((c) => selectedColumns.includes(c.id))) {
        expect(checkedLabels).toContain(col.label);
      }
    });

    it("non-selected columns have unchecked checkboxes", () => {
      const selectedColumns: ColumnId[] = ["level", "message"];
      const { getByTestId, getAllByRole } = renderPicker({ selectedColumns });
      fireEvent.click(getByTestId("column-picker"));

      const checkboxes = getAllByRole("checkbox") as HTMLInputElement[];
      const uncheckedLabels = checkboxes
        .filter((cb) => !cb.checked)
        .map((cb) => cb.closest("label")?.textContent?.trim());

      for (const col of COLUMNS.filter((c) => !selectedColumns.includes(c.id))) {
        expect(uncheckedLabels).toContain(col.label);
      }
    });
  });

  describe("disabled state", () => {
    it("required columns have disabled checkboxes", () => {
      const { getByTestId, getAllByRole } = renderPicker();
      fireEvent.click(getByTestId("column-picker"));

      const checkboxes = getAllByRole("checkbox") as HTMLInputElement[];
      for (const checkbox of checkboxes) {
        const label = checkbox.closest("label")?.textContent?.trim() ?? "";
        const col = COLUMNS.find((c) => c.label === label);
        if (col && REQUIRED_COLUMNS.has(col.id)) {
          expect(checkbox.disabled).toBe(true);
        }
      }
    });

    it("viewport-hidden columns have disabled checkboxes", () => {
      const viewportHidden = new Set<ColumnId>(["app", "instance"]);
      const { getByTestId, getAllByRole } = renderPicker({ viewportHidden });
      fireEvent.click(getByTestId("column-picker"));

      const checkboxes = getAllByRole("checkbox") as HTMLInputElement[];
      for (const checkbox of checkboxes) {
        const label = checkbox.closest("label")?.textContent?.trim() ?? "";
        const col = COLUMNS.find((c) => c.label === label);
        if (col && viewportHidden.has(col.id)) {
          expect(checkbox.disabled).toBe(true);
        }
      }
    });

    it("viewport-hidden columns have title 'Hidden at this screen size' on their label", () => {
      const viewportHidden = new Set<ColumnId>(["app"]);
      const { getByTestId, getAllByRole } = renderPicker({ viewportHidden });
      fireEvent.click(getByTestId("column-picker"));

      const checkboxes = getAllByRole("checkbox") as HTMLInputElement[];
      for (const checkbox of checkboxes) {
        const labelEl = checkbox.closest("label") as HTMLElement | null;
        const label = labelEl?.textContent?.trim() ?? "";
        const col = COLUMNS.find((c) => c.label === label);
        if (col && viewportHidden.has(col.id)) {
          expect(labelEl?.title).toBe("Hidden at this screen size");
        }
      }
    });

    it("non-required, non-hidden columns are not disabled", () => {
      // "app" and "function" are optional and not viewport-hidden
      const { getByTestId, getAllByRole } = renderPicker({
        viewportHidden: new Set<ColumnId>(),
      });
      fireEvent.click(getByTestId("column-picker"));

      const checkboxes = getAllByRole("checkbox") as HTMLInputElement[];
      for (const checkbox of checkboxes) {
        const label = checkbox.closest("label")?.textContent?.trim() ?? "";
        const col = COLUMNS.find((c) => c.label === label);
        if (col && !REQUIRED_COLUMNS.has(col.id)) {
          expect(checkbox.disabled).toBe(false);
        }
      }
    });
  });

  describe("interactions", () => {
    it("clicking a non-disabled checkbox calls onToggle with the column id", () => {
      const onToggle = vi.fn();
      // Use "app" which is optional and not required
      const { getByTestId, getAllByRole } = renderPicker({
        onToggle,
        viewportHidden: new Set<ColumnId>(),
      });
      fireEvent.click(getByTestId("column-picker"));

      const checkboxes = getAllByRole("checkbox") as HTMLInputElement[];
      const appCheckbox = checkboxes.find((cb) => {
        const label = cb.closest("label")?.textContent?.trim() ?? "";
        return label === "App";
      });
      expect(appCheckbox).not.toBeUndefined();
      expect(appCheckbox!.disabled).toBe(false);

      fireEvent.click(appCheckbox!);
      expect(onToggle).toHaveBeenCalledWith("app");
    });

    it("required checkboxes are disabled so browsers cannot fire their onChange", () => {
      // jsdom's fireEvent bypasses the native disabled guard, so we assert the
      // disabled attribute itself — which is what prevents onChange in real browsers.
      const { getByTestId, getAllByRole } = renderPicker();
      fireEvent.click(getByTestId("column-picker"));

      const checkboxes = getAllByRole("checkbox") as HTMLInputElement[];
      const requiredCheckboxes = checkboxes.filter((cb) => {
        const label = cb.closest("label")?.textContent?.trim() ?? "";
        const col = COLUMNS.find((c) => c.label === label);
        return col !== undefined && REQUIRED_COLUMNS.has(col.id);
      });

      expect(requiredCheckboxes.length).toBeGreaterThan(0);
      for (const cb of requiredCheckboxes) {
        expect(cb.disabled).toBe(true);
      }
    });

    it("'Reset to defaults' button calls onReset when clicked", () => {
      const onReset = vi.fn();
      const { getByTestId, getByRole } = renderPicker({ onReset });
      fireEvent.click(getByTestId("column-picker"));

      const resetBtn = getByRole("button", { name: /reset to defaults/i });
      fireEvent.click(resetBtn);
      expect(onReset).toHaveBeenCalledTimes(1);
    });
  });
});
