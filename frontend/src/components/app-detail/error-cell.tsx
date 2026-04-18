/**
 * ErrorCell renders the error message + a "Traceback" toggle button.
 * The actual traceback `<pre>` is rendered as a separate `<tr>` by the parent
 * table component — this cell just controls the toggle state.
 */

interface Props {
  traceback?: string | null;
  message?: string | null;
  expanded: boolean;
  onToggle: () => void;
}

export function ErrorCell({ traceback, message, expanded, onToggle }: Props) {
  if (!traceback) return <>{message ?? "—"}</>;

  return (
    <div class="ht-error-cell">
      <span>{message ?? "Error"}</span>
      <button
        type="button"
        class="ht-btn ht-btn--xs ht-btn--ghost ht-traceback-toggle"
        onClick={(e) => { e.stopPropagation(); onToggle(); }}
        aria-expanded={expanded}
        aria-label={expanded ? "Hide traceback" : "Show traceback"}
      >
        {expanded ? "Hide traceback" : "Traceback"}
      </button>
    </div>
  );
}
