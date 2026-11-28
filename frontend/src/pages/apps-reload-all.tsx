import { useState } from "react";
import { toast } from "sonner";

import { reloadAllApps, type ReloadAllResponse } from "@/api/endpoints";
import { IconRefresh } from "@/components/shared/icons";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { useAsyncAction } from "@/hooks/use-async-action";
import { pluralize } from "@/utils/format";

/** The toast for a reload-all that ran: its counts, then each app that didn't succeed. */
export function reloadAllSummary(response: ReloadAllResponse): string {
  const { succeeded, failed, refused } = response.counts;
  const summary = `Reloaded ${pluralize(response.apps.length, "app")}: ${succeeded} succeeded, ${failed} failed, ${refused} refused`;
  const notOk = response.apps
    .filter((app) => app.result !== "succeeded")
    .map((app) => `${app.app_key} (${app.result})`);
  return notOk.length > 0 ? `${summary}. ${notOk.join(", ")}` : summary;
}

// The request returns once every app has restarted, so the dialog closes at once and the button
// shows the request in flight. App status changes arrive over the WebSocket meanwhile.
async function performReloadAll() {
  let response: ReloadAllResponse;
  try {
    response = await reloadAllApps();
  } catch (err) {
    // A refusal's detail is the whole story: the file and line, the config error, or the busy app.
    toast.error(`Reload all refused: ${err instanceof Error ? err.message : String(err)}`);
    // Rethrown for useAsyncAction, which records it and resets `loading`; it shows no toast of its own.
    throw err;
  }
  const message = reloadAllSummary(response);
  if (response.counts.failed > 0 || response.counts.refused > 0) toast.error(message);
  else toast.success(message);
}

/** "Reload all" in the Apps page header: re-reads the config and re-imports every app, behind a confirm. */
export function ReloadAllButton() {
  const { loading, run } = useAsyncAction();
  const [confirming, setConfirming] = useState(false);

  return (
    <>
      <Button
        variant="outline"
        size="sm"
        className="ml-auto"
        disabled={loading}
        onClick={() => setConfirming(true)}
        data-testid="btn-reload-all"
      >
        <IconRefresh /> {loading ? "Reloading…" : "Reload all"}
      </Button>
      <AlertDialog open={confirming} onOpenChange={setConfirming}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reload every app?</AlertDialogTitle>
            <AlertDialogDescription>
              Re-reads the config and re-imports every app and the helpers they import, then restarts every running or
              failed app. Hassette and its Home Assistant connection stay up. Nothing stops if the config is invalid or
              a file has a syntax error.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction data-testid="confirm-reload-all" onClick={() => void run(performReloadAll)}>
              Reload all
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
