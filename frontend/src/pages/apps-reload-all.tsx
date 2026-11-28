import { useState } from "react";
import { toast } from "sonner";

import { ApiError } from "@/api/client";
import { reloadAllApps, type ReloadAllResponse } from "@/api/endpoints";
import type { components } from "@/api/generated-types";
import { actionOutcome } from "@/components/shared/action-buttons";
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

type ProblemCode = components["schemas"]["ProblemCode"];

/**
 * The codes of a reload-all refused before anything ran; any other error leaves the outcome unknown. Kept in step
 * with `RELOAD_ALL_CODES` in `src/hassette/web/routes/apps.py`: a refusal code missing here reads as "may not have
 * finished".
 */
const REFUSAL_CODES: ReadonlySet<string> = new Set<ProblemCode>([
  "action_in_progress",
  "bootstrap_not_released",
  "reload_config_invalid",
  "reload_syntax_error",
]);

/** What a reload-all did to how many apps, e.g. "5 apps reloaded, 1 app stopped"; unknown actions print as sent. */
function actionSummary(response: ReloadAllResponse): string {
  const counts = new Map<string, number>();
  for (const app of response.apps) counts.set(app.action, (counts.get(app.action) ?? 0) + 1);
  const parts = [...counts].map(([action, n]) => `${pluralize(n, "app")} ${actionOutcome(action) ?? action}`);
  return parts.length > 0 ? parts.join(", ") : "no apps affected";
}

/** The toast for a reload-all that ran: what it did, its counts, then each app that didn't succeed. */
export function reloadAllSummary(response: ReloadAllResponse): string {
  const { succeeded, failed, refused } = response.counts;
  const summary = `Reload all: ${actionSummary(response)}; ${succeeded} succeeded, ${failed} failed, ${refused} refused`;
  const notOk = response.apps
    .filter((app) => app.result !== "succeeded")
    .map((app) => `${app.app_key} (${app.result})`);
  return notOk.length > 0 ? `${summary}. ${notOk.join(", ")}` : summary;
}

/** The toast for a reload-all request that threw: a refusal says nothing ran, anything else that it may not have. */
export function reloadAllErrorMessage(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  if (err instanceof ApiError && err.code !== undefined && REFUSAL_CODES.has(err.code)) {
    // A refusal's detail is the whole story: the file and line, the config error, or the busy app.
    return `Reload all refused: ${message}`;
  }
  // A timeout, a dropped connection or a server error can come after apps stopped, so the outcome is unknown.
  return `Reload all may not have finished: ${message}. Check the app list for each app's status.`;
}

// The request returns once every app has restarted, so the dialog closes at once and the button
// shows the request in flight. App status changes arrive over the WebSocket meanwhile.
async function performReloadAll() {
  let response: ReloadAllResponse;
  try {
    response = await reloadAllApps();
  } catch (err) {
    toast.error(reloadAllErrorMessage(err));
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
