import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";

interface Props {
  errorMessage: string;
  errorTraceback: string | null;
}

export function ErrorDisplay({ errorMessage, errorTraceback }: Props) {
  const tbOpen = useRef(signal(false)).current;

  return (
    <div class="ht-card ht-mb-4" data-testid="error-display">
      <p class="ht-text-danger">
        <strong>Error:</strong> {errorMessage}
      </p>
      {errorTraceback && (
        <div>
          <button
            class="ht-btn ht-btn--sm ht-mt-3"
            onClick={() => { tbOpen.value = !tbOpen.value; }}
            aria-expanded={tbOpen.value}
          >
            {tbOpen.value ? "Hide traceback" : "Show traceback"}
          </button>
          {tbOpen.value && (
            <pre class="ht-traceback">{errorTraceback}</pre>
          )}
        </div>
      )}
    </div>
  );
}
