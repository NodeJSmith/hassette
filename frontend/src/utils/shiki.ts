import type { HighlighterGeneric } from "shiki";

/** Theme pair used everywhere we highlight source with Shiki (code tab, config tab). */
export const SHIKI_THEMES = { light: "github-light", dark: "github-dark" } as const;

const highlighterCache = new Map<string, Promise<HighlighterGeneric<never, never>>>();

/**
 * Returns a cached Shiki highlighter for a single language, creating it lazily on
 * first use. Each language gets its own cache entry so loading one grammar (e.g.
 * "toml" for the config tab) never blocks or evicts another (e.g. "python" for the
 * code tab).
 *
 * On failure the cache entry is dropped so the next call retries instead of
 * replaying a rejected promise forever.
 */
export function getShikiHighlighter(lang: string): Promise<HighlighterGeneric<never, never>> {
  const cached = highlighterCache.get(lang);
  if (cached) return cached;

  const promise = import("shiki")
    .then(({ createHighlighter }) =>
      createHighlighter({
        langs: [lang],
        themes: [SHIKI_THEMES.light, SHIKI_THEMES.dark],
      }),
    )
    .catch((e) => {
      highlighterCache.delete(lang);
      throw e;
    });

  highlighterCache.set(lang, promise);
  return promise;
}
