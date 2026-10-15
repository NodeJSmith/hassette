import { describe, expect, it } from "vitest";

import { parseRstInline, roleTargetText } from "./rst-inline";

const code = (text: string) => ({ kind: "code", text });
const plain = (text: string) => ({ kind: "text", text });

describe("parseRstInline", () => {
  it("returns plain text unchanged", () => {
    expect(parseRstInline("Just words.")).toEqual([plain("Just words.")]);
  });

  it("renders a double-backtick literal as inline code", () => {
    expect(parseRstInline('the effective behavior is ``"warn"``.')).toEqual([
      plain("the effective behavior is "),
      code('"warn"'),
      plain("."),
    ]);
  });

  it("does not read markup inside a literal", () => {
    expect(parseRstInline("serving any ``/api/*`` route *now*")).toEqual([
      plain("serving any "),
      code("/api/*"),
      plain(" route now"),
    ]);
  });

  it("renders a ~-prefixed role target as its last dotted segment", () => {
    expect(parseRstInline("A :class:`~pydantic.SecretStr` value")).toEqual([
      plain("A "),
      code("SecretStr"),
      plain(" value"),
    ]);
  });

  it("renders a role target without ~ as the full target", () => {
    expect(parseRstInline(":class:`aiohttp.ClientTimeout`")).toEqual([code("aiohttp.ClientTimeout")]);
  });

  it.each(["func", "meth", "attr", "data", "mod", "exc", "py:class", "obj"])("handles the :%s: role", (role) => {
    expect(parseRstInline(`see :${role}:\`pkg.mod.Thing\``)).toEqual([plain("see "), code("pkg.mod.Thing")]);
  });

  it("strips single-backtick interpreted text to plain text", () => {
    expect(parseRstInline("when `enabled` is set")).toEqual([plain("when enabled is set")]);
  });

  it("strips hyperlink references to their title", () => {
    expect(parseRstInline("See `the docs <https://example.com>`_ and `Name`_.")).toEqual([
      plain("See the docs and Name."),
    ]);
  });

  it("strips strong and emphasis markers", () => {
    expect(parseRstInline("a **bold** and *value* claim")).toEqual([plain("a bold and value claim")]);
  });

  it("leaves bare asterisks that are not emphasis alone", () => {
    expect(parseRstInline("match light.* or 2 * 3")).toEqual([plain("match light.* or 2 * 3")]);
  });

  it("removes directive lines and literal-block markers", () => {
    const source = "Example::\n\n    x = 1\n\nOr this:\n\n.. code-block:: toml\n\n    [a]\n";
    expect(parseRstInline(source)).toEqual([plain("Example:\n\n    x = 1\n\nOr this:\n\n\n    [a]\n")]);
  });

  it("leaves no literal markup in a real config description", () => {
    const source =
      'When ``None`` (default), the effective behavior is ``"warn"``. Stored as :class:`~pydantic.SecretStr`.';
    const segments = parseRstInline(source);
    expect(segments).toEqual([
      plain("When "),
      code("None"),
      plain(" (default), the effective behavior is "),
      code('"warn"'),
      plain(". Stored as "),
      code("SecretStr"),
      plain("."),
    ]);
    expect(segments.map((s) => s.text).join("")).not.toMatch(/[`:]class:|``/);
  });
});

describe("roleTargetText", () => {
  it("prefers an explicit title", () => {
    expect(roleTargetText("the client <hassette.Client>")).toBe("the client");
  });

  it("drops the ! cross-reference suppression prefix", () => {
    expect(roleTargetText("!pkg.Thing")).toBe("pkg.Thing");
  });

  it("shortens a ~ method target to the method name", () => {
    expect(roleTargetText("~hassette.core.api_resource.ApiResource.rest_request")).toBe("rest_request");
  });
});
