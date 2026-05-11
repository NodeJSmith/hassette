import { describe, expect, it, vi } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/preact";
import { ConfirmDialog } from "./confirm-dialog";

function renderDialog(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const props = {
    title: "Delete item",
    body: "Are you sure you want to delete this item?",
    confirmLabel: "Delete",
    onConfirm: vi.fn(),
    onCancel: vi.fn(),
    ...overrides,
  };
  return { ...render(<ConfirmDialog {...props} />), props };
}

describe("ConfirmDialog — rendering", () => {
  it("renders the title", () => {
    const { getByText } = renderDialog();
    expect(getByText("Delete item")).toBeDefined();
  });

  it("renders the body text", () => {
    const { getByText } = renderDialog();
    expect(getByText("Are you sure you want to delete this item?")).toBeDefined();
  });

  it("renders the confirm button with the provided label", () => {
    const { getByText } = renderDialog({ confirmLabel: "Remove" });
    expect(getByText("Remove")).toBeDefined();
  });

  it("renders a Cancel button", () => {
    const { getByText } = renderDialog();
    expect(getByText("Cancel")).toBeDefined();
  });

  it("has role=dialog and aria-modal=true", () => {
    const { container } = renderDialog();
    const dialog = container.querySelector("[role='dialog']");
    expect(dialog).not.toBeNull();
    expect(dialog!.getAttribute("aria-modal")).toBe("true");
  });

  it("has aria-labelledby pointing to the title element", () => {
    const { container } = renderDialog();
    const dialog = container.querySelector("[role='dialog']");
    const labelledById = dialog!.getAttribute("aria-labelledby");
    expect(labelledById).not.toBeNull();
    const titleEl = container.querySelector(`#${labelledById}`);
    expect(titleEl).not.toBeNull();
    expect(titleEl!.textContent).toBe("Delete item");
  });

  it("has aria-describedby pointing to the body element", () => {
    const { container } = renderDialog();
    const dialog = container.querySelector("[role='dialog']");
    const describedById = dialog!.getAttribute("aria-describedby");
    expect(describedById).not.toBeNull();
    const bodyEl = container.querySelector(`#${describedById}`);
    expect(bodyEl).not.toBeNull();
    expect(bodyEl!.textContent).toContain("Are you sure");
  });
});

describe("ConfirmDialog — interactions", () => {
  it("calls onConfirm when confirm button is clicked", () => {
    const { getByText, props } = renderDialog();
    fireEvent.click(getByText("Delete"));
    expect(props.onConfirm).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when cancel button is clicked", () => {
    const { getByText, props } = renderDialog();
    fireEvent.click(getByText("Cancel"));
    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when Escape key is pressed", () => {
    const { props } = renderDialog();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when backdrop is clicked", () => {
    const { container, props } = renderDialog();
    const backdrop = container.querySelector(".ht-confirm-dialog__backdrop");
    expect(backdrop).not.toBeNull();
    fireEvent.click(backdrop!);
    expect(props.onCancel).toHaveBeenCalledTimes(1);
  });
});

describe("ConfirmDialog — tone", () => {
  it("default tone does not apply danger class to confirm button", () => {
    const { getByText } = renderDialog({ tone: "default" });
    const confirmBtn = getByText("Delete");
    expect(confirmBtn.className).not.toContain("ht-confirm-dialog__confirm--danger");
  });

  it("danger tone applies danger class to confirm button", () => {
    const { getByText } = renderDialog({ tone: "danger" });
    const confirmBtn = getByText("Delete");
    expect(confirmBtn.className).toContain("ht-confirm-dialog__confirm--danger");
  });
});

describe("ConfirmDialog — focus management", () => {
  it("moves focus to the Cancel button on mount", async () => {
    const { getByText } = renderDialog();
    const cancelBtn = getByText("Cancel");
    await waitFor(() => {
      expect(document.activeElement).toBe(cancelBtn);
    });
  });
});
