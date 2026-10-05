import { useEffect } from "react";
import { toast } from "sonner";

import { useAppStore } from "../state/store";

/** Fixed id so a second detection updates the same toast instead of stacking another. */
export const SERVER_UPDATED_TOAST_ID = "server-updated";

/**
 * Shows a persistent reload prompt once the server reports a different version than this tab loaded
 * against. A prompt rather than an automatic reload, so nothing the user is doing is lost.
 */
export function useServerUpdatePrompt(): void {
  const serverUpdated = useAppStore((s) => s.serverUpdated);

  useEffect(() => {
    if (!serverUpdated) return;
    toast.info("Hassette was updated", {
      id: SERVER_UPDATED_TOAST_ID,
      description: "Reload to use the matching dashboard.",
      duration: Number.POSITIVE_INFINITY,
      action: { label: "Reload", onClick: () => window.location.reload() },
    });
  }, [serverUpdated]);
}
