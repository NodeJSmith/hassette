import type { MouseEvent as ReactMouseEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

/** How long the ✓ confirmation stays up after a copy. */
export const COPY_CONFIRM_MS = 1500;

interface Props {
  text: string;
  label: string;
}

/** Inline copy-to-clipboard glyph that confirms with a ✓; sits on the line of the value it copies. */
export function CopyButton({ text, label }: Props) {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  // A new value hasn't been copied yet; the cleanup also drops a pending dismissal on unmount.
  useEffect(() => {
    setCopied(false);
    return () => clearTimeout(timeoutRef.current);
  }, [text]);

  const handleCopy = useCallback(
    async (e: ReactMouseEvent) => {
      e.stopPropagation();
      try {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        clearTimeout(timeoutRef.current);
        timeoutRef.current = setTimeout(() => {
          setCopied(false);
        }, COPY_CONFIRM_MS);
      } catch {
        /* clipboard unavailable */
      }
    },
    [text],
  );

  return (
    <Button variant="ghost" size="inline" onClick={handleCopy} aria-label={label} title={copied ? "Copied" : label}>
      {copied ? "✓" : "⧉"}
    </Button>
  );
}
