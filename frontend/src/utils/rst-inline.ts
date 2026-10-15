/**
 * Reduce reStructuredText docstring markup to a small displayable subset.
 *
 * Config field descriptions come from Python docstrings written in RST: hassette's own config
 * and, through ``use_attribute_docstrings``, user ``AppConfig`` fields. The UI renders only two
 * things from that markup: inline literals and Sphinx role targets, both as inline code.
 * Emphasis, strong, backtick interpreted text and hyperlink references, directive lines, and
 * literal-block markers are stripped to plain text.
 *
 * This is a best-effort subset, not an RST parser. Rarer constructs (suffix-form roles,
 * backslash escapes, hyperlink target lines, bare ``name_`` references, footnotes,
 * substitutions) pass through as literal text. Hassette's own descriptions use only literals
 * and prefix roles; full fidelity would need docutils on the backend, which a help popover
 * does not justify.
 */

export type RstSegment = { kind: "text"; text: string } | { kind: "code"; text: string };

const DIRECTIVE_LINE = /^[ \t]*\.\. [\w:-]+::.*(?:\n|$)/gm;
const BARE_LITERAL_MARKER_LINE = /^[ \t]*::[ \t]*(?:\n|$)/gm;
const SPACED_LITERAL_MARKER = /[ \t]+::[ \t]*$/gm;
const TRAILING_LITERAL_MARKER = /(\S)::[ \t]*$/gm;

/**
 * One alternation scanned left to right, so a literal's contents are never re-read as
 * other markup (``/api/*`` stays intact). Capture groups, in order:
 * 1 inline literal, 2 role target, 3 interpreted text / hyperlink reference,
 * 4 strong, 5 emphasis.
 */
const INLINE_MARKUP =
  /``(.+?)``|(?::[A-Za-z][\w+.-]*)+:`([^`]+)`|`([^`]+)`_{0,2}|\*\*(\S(?:.*?\S)?)\*\*|(?<![\w*])\*(\S(?:.*?\S)?)\*(?![\w*])/gs;

/** Split `Title <target>` (explicit-title syntax used by roles and hyperlinks). */
const EXPLICIT_TITLE = /^(.*?)\s*<([^<>]+)>$/s;

/**
 * Display text for a Sphinx role target: an explicit title wins, a leading `~` keeps only the
 * last dotted segment, and the `!` (suppress cross-reference) prefix is dropped.
 */
export function roleTargetText(target: string): string {
  const titled = EXPLICIT_TITLE.exec(target);
  if (titled && titled[1]) return titled[1];
  const bare = target.replace(/^!/, "");
  if (!bare.startsWith("~")) return bare;
  const parts = bare.slice(1).split(".");
  return parts[parts.length - 1];
}

/** Text shown for interpreted text or a hyperlink reference: the title, never the URL. */
function referenceText(content: string): string {
  const titled = EXPLICIT_TITLE.exec(content);
  return titled && titled[1] ? titled[1] : content;
}

function stripBlockMarkup(text: string): string {
  return text
    .replace(DIRECTIVE_LINE, "")
    .replace(BARE_LITERAL_MARKER_LINE, "")
    .replace(SPACED_LITERAL_MARKER, "")
    .replace(TRAILING_LITERAL_MARKER, "$1:");
}

/** Parse RST docstring text into plain-text and inline-code segments. */
export function parseRstInline(source: string): RstSegment[] {
  const text = stripBlockMarkup(source);
  const segments: RstSegment[] = [];
  let pending = "";
  let last = 0;

  for (const match of text.matchAll(INLINE_MARKUP)) {
    pending += text.slice(last, match.index);
    last = match.index + match[0].length;
    const [, literal, role, reference, strong, emphasis] = match;
    const code = literal ?? (role !== undefined ? roleTargetText(role) : undefined);
    if (code !== undefined) {
      if (pending) segments.push({ kind: "text", text: pending });
      pending = "";
      segments.push({ kind: "code", text: code });
    } else {
      pending += reference !== undefined ? referenceText(reference) : (strong ?? emphasis);
    }
  }

  pending += text.slice(last);
  if (pending) segments.push({ kind: "text", text: pending });
  return segments;
}
