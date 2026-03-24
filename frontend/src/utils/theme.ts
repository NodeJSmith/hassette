/** Valid theme values for the Hassette UI. */
export type Theme = "dark" | "light";

const THEMES: ReadonlySet<string> = new Set<string>(["dark", "light"]);

/** Runtime type guard for theme values stored in localStorage. */
export function isTheme(v: unknown): v is Theme {
  return typeof v === "string" && THEMES.has(v);
}
