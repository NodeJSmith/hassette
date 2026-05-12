/**
 * ErrorCell renders the error message + a "Traceback" toggle button.
 * The actual traceback `<pre>` is rendered as a separate `<tr>` by the parent
 * table component — this cell just controls the toggle state.
 */
import { Button } from "../shared/button";
import styles from "./error-cell.module.css";

interface Props {
  traceback?: string | null;
  message?: string | null;
  expanded: boolean;
  onToggle: () => void;
}

export function ErrorCell({ traceback, message, expanded, onToggle }: Props) {
  if (!traceback) return <>{message ?? "—"}</>;

  return (
    <div class={styles.errorCell}>
      <span>{message ?? "Error"}</span>
      <Button
        ghost
        size="xs"
        class={styles.tracebackToggle}
        onClick={(e) => { e.stopPropagation(); onToggle(); }}
        aria-expanded={expanded}
        aria-label={expanded ? "Hide traceback" : "Show traceback"}
      >
        {expanded ? "hide traceback" : "show traceback"}
      </Button>
    </div>
  );
}
