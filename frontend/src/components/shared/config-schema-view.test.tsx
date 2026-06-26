import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";

import type { SchemaNode } from "../../api/config-view-types";
import { ConfigSchemaView } from "./config-schema-view";

describe("ConfigSchemaView", () => {
  describe("ui.order", () => {
    it("reorders scalar fields by ui.order, overriding declaration order", () => {
      // Declaration order is [alpha, beta] but ui.order flips them to [beta, alpha].
      const schema: SchemaNode = {
        type: "object",
        properties: {
          alpha: { type: "string", title: "Alpha", ui: { order: 2 } },
          beta: { type: "string", title: "Beta", ui: { order: 1 } },
        },
      };
      const { container } = render(<ConfigSchemaView schema={schema} values={{ alpha: "a", beta: "b" }} />);
      const order = [...container.querySelectorAll("[data-testid^='config-field-']")].map((el) =>
        el.getAttribute("data-testid"),
      );
      expect(order).toEqual(["config-field-beta", "config-field-alpha"]);
    });

    it("falls back to declaration order when ui.order is absent", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          first: { type: "string", title: "First" },
          second: { type: "string", title: "Second" },
        },
      };
      const { container } = render(<ConfigSchemaView schema={schema} values={{ first: "1", second: "2" }} />);
      const order = [...container.querySelectorAll("[data-testid^='config-field-']")].map((el) =>
        el.getAttribute("data-testid"),
      );
      expect(order).toEqual(["config-field-first", "config-field-second"]);
    });

    it("reorders group sections by ui.order", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          alpha_group: {
            type: "object",
            title: "Alpha Group",
            ui: { order: 2 },
            properties: { x: { type: "string", title: "X" } },
          },
          beta_group: {
            type: "object",
            title: "Beta Group",
            ui: { order: 1 },
            properties: { y: { type: "string", title: "Y" } },
          },
        },
      };
      const values = { alpha_group: { x: "1" }, beta_group: { y: "2" } };
      const { container } = render(<ConfigSchemaView schema={schema} values={values} />);
      const sections = [...container.querySelectorAll("[data-testid^='config-section-']")].map((el) =>
        el.getAttribute("data-testid"),
      );
      expect(sections).toEqual(["config-section-beta-group", "config-section-alpha-group"]);
    });
  });

  describe("ui.widget", () => {
    it("forces path (code-styled) rendering when ui.widget is 'path'", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          some_value: { type: "string", title: "Some Value", ui: { widget: "path" } },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ some_value: "abc/def" }} />);
      const cell = getByTestId("config-value-some_value");
      // The path widget renders the value inside a <code> element; a plain string does not.
      expect(cell.querySelector("code")).not.toBeNull();
      expect(cell.textContent).toContain("abc/def");
    });

    it("renders a plain string without the path widget when ui.widget is absent", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          some_value: { type: "string", title: "Some Value" },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ some_value: "plainstring" }} />);
      const cell = getByTestId("config-value-some_value");
      expect(cell.querySelector("code")).toBeNull();
      expect(cell.textContent).toContain("plainstring");
    });
  });

  describe("ui.label", () => {
    it("uses ui.label as the field display name, overriding the humanized key", () => {
      // The label differs from humanizeKey("foo_bar") ("Foo Bar"), so a broken
      // ui.label path would fail this assertion.
      const schema: SchemaNode = {
        type: "object",
        properties: {
          foo_bar: { type: "string", title: "Foo Bar", ui: { label: "Custom Override" } },
        },
      };
      const { getByText, queryByText } = render(<ConfigSchemaView schema={schema} values={{ foo_bar: "x" }} />);
      expect(getByText("Custom Override")).toBeDefined();
      expect(queryByText("Foo Bar")).toBeNull();
    });

    it("uses the humanized field name when ui.label is absent", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          retention_days: { type: "number", title: "Retention Days" },
        },
      };
      const { getByText } = render(<ConfigSchemaView schema={schema} values={{ retention_days: 7 }} />);
      expect(getByText("Retention Days")).toBeDefined();
    });
  });
});
