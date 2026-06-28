import { fireEvent, render } from "@testing-library/preact";
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

  describe("section grouping", () => {
    it("collects scalar fields under a capitalized 'General' section", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          foo: { type: "string", title: "Foo" },
        },
      };
      const { getByTestId, getByText } = render(<ConfigSchemaView schema={schema} values={{ foo: "x" }} />);
      expect(getByTestId("config-section-general")).toBeDefined();
      // The section title is "General" (capitalized), not the hardcoded lowercase "general".
      expect(getByText("General")).toBeDefined();
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

  describe("enum formatting (FR#9)", () => {
    it("renders an enum field's value as a badge", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          log_format: { type: "string", title: "Log Format", enum: ["auto", "console", "json"] },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ log_format: "auto" }} />);
      const cell = getByTestId("config-value-log_format");
      expect(cell.textContent).toContain("auto");
      // Rendered through Badge (neutral variant), not the plain-string span.
      expect(cell.querySelector("span")?.className).toMatch(/neutral/);
    });

    it("detects an enum nested inside an anyOf branch (StrEnum | None)", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          behavior: {
            title: "Behavior",
            anyOf: [{ type: "string", enum: ["ignore", "warn", "error"] }, { type: "null" }],
          },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ behavior: "warn" }} />);
      const cell = getByTestId("config-value-behavior");
      expect(cell.textContent).toContain("warn");
      expect(cell.querySelector("span")?.className).toMatch(/neutral/);
    });
  });

  describe("duration formatting (FR#9)", () => {
    it("humanizes a _seconds field above a minute", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          startup_timeout_seconds: { type: "integer", title: "Startup Timeout Seconds" },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ startup_timeout_seconds: 90 }} />);
      expect(getByTestId("config-value-startup_timeout_seconds").textContent).toContain("1m 30s");
    });

    it("renders a sub-minute _seconds field as seconds", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          reconnect_delay_seconds: { type: "number", title: "Reconnect Delay Seconds" },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ reconnect_delay_seconds: 30 }} />);
      expect(getByTestId("config-value-reconnect_delay_seconds").textContent).toContain("30s");
    });

    it("renders a _milliseconds field in ms", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          debounce_milliseconds: { type: "integer", title: "Debounce Milliseconds" },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ debounce_milliseconds: 500 }} />);
      expect(getByTestId("config-value-debounce_milliseconds").textContent).toContain("500ms");
    });

    it("leaves a plain number field unformatted", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          job_history_size: { type: "integer", title: "Job History Size" },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ job_history_size: 1000 }} />);
      const text = getByTestId("config-value-job_history_size").textContent ?? "";
      expect(text).toContain("1000");
      expect(text).not.toMatch(/s$|ms$/);
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

  describe("boolean rendering", () => {
    it("renders booleans as true/false, not yes/no", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          enabled: { type: "boolean", title: "Enabled" },
          disabled: { type: "boolean", title: "Disabled" },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ enabled: true, disabled: false }} />);
      expect(getByTestId("config-value-enabled").textContent).toBe("true");
      expect(getByTestId("config-value-disabled").textContent).toBe("false");
    });
  });

  describe("framework field partitioning", () => {
    const schema: SchemaNode = {
      type: "object",
      properties: {
        brightness: { type: "integer", title: "Brightness" },
        zone: { type: "string", title: "Zone" },
        instance_name: { type: "string", title: "Instance Name" },
        log_level: { type: "string", title: "Log Level" },
        enabled: { type: "boolean", title: "Enabled" },
        autostart: { type: "boolean", title: "Autostart" },
      },
    };
    const values = {
      brightness: 100,
      zone: "kitchen",
      instance_name: "MyApp.0",
      log_level: "INFO",
      enabled: true,
      autostart: true,
    };
    const frameworkFields = ["instance_name", "log_level", "app_key", "enabled", "autostart"];

    it("renders user fields under 'App Settings' when frameworkFields is provided", () => {
      const { getByTestId } = render(
        <ConfigSchemaView schema={schema} values={values} frameworkFields={frameworkFields} />,
      );
      const appSection = getByTestId("config-section-app-settings");
      expect(appSection.querySelector("[data-testid='config-field-brightness']")).not.toBeNull();
      expect(appSection.querySelector("[data-testid='config-field-zone']")).not.toBeNull();
      expect(appSection.querySelector("[data-testid='config-field-instance_name']")).toBeNull();
    });

    it("renders framework fields under 'Hassette Settings'", () => {
      const { getByTestId } = render(
        <ConfigSchemaView schema={schema} values={values} frameworkFields={frameworkFields} />,
      );
      const fwSection = getByTestId("config-section-hassette-settings");
      expect(fwSection.querySelector("[data-testid='config-field-instance_name']")).not.toBeNull();
      expect(fwSection.querySelector("[data-testid='config-field-log_level']")).not.toBeNull();
      expect(fwSection.querySelector("[data-testid='config-field-enabled']")).not.toBeNull();
      expect(fwSection.querySelector("[data-testid='config-field-autostart']")).not.toBeNull();
      expect(fwSection.querySelector("[data-testid='config-field-brightness']")).toBeNull();
    });

    it("uses 'General' section title when frameworkFields is not provided", () => {
      const { getByTestId, queryByTestId } = render(<ConfigSchemaView schema={schema} values={values} />);
      expect(getByTestId("config-section-general")).toBeDefined();
      expect(queryByTestId("config-section-app-settings")).toBeNull();
      expect(queryByTestId("config-section-hassette-settings")).toBeNull();
    });

    it("applies de-emphasis to the framework section", () => {
      const { getByTestId } = render(
        <ConfigSchemaView schema={schema} values={values} frameworkFields={frameworkFields} />,
      );
      const fwSection = getByTestId("config-section-hassette-settings");
      expect(fwSection.className).toMatch(/secondary/);
    });
  });

  describe("machine key", () => {
    it("shows the raw field key inline as a <code> element", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          log_level: { type: "string", title: "Log Level", ui: { label: "Log Level" } },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ log_level: "info" }} />);
      // The only <code> in a plain-string row is the machine key (the value renders as a span).
      const code = getByTestId("config-field-log_level").querySelector("code");
      expect(code?.textContent).toBe("log_level");
    });
  });

  describe("help popover", () => {
    it("reveals the description in a popover only after the info button is clicked", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          some_value: { type: "string", title: "Some Value", description: "Helpful context." },
        },
      };
      const { getByTestId, queryByTestId } = render(<ConfigSchemaView schema={schema} values={{ some_value: "x" }} />);
      // Help is hidden until requested.
      expect(queryByTestId("field-help")).toBeNull();

      const toggle = getByTestId("config-field-some_value").querySelector("button[aria-expanded]");
      if (!(toggle instanceof Element)) throw new Error("expected an info toggle button");
      expect(toggle.getAttribute("aria-expanded")).toBe("false");

      fireEvent.click(toggle);

      expect(getByTestId("field-help").textContent).toContain("Helpful context.");
      expect(toggle.getAttribute("aria-expanded")).toBe("true");
    });

    it("renders no info button when a field has no description", () => {
      const schema: SchemaNode = {
        type: "object",
        properties: {
          some_value: { type: "string", title: "Some Value" },
        },
      };
      const { getByTestId } = render(<ConfigSchemaView schema={schema} values={{ some_value: "x" }} />);
      expect(getByTestId("config-field-some_value").querySelector("button[aria-expanded]")).toBeNull();
    });
  });
});
