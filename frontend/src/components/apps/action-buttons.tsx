import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { reloadApp, startApp, stopApp } from "../../api/endpoints";
import { ConfirmDialog } from "../shared/confirm-dialog";
import { IconPlay, IconRefresh, IconSquare } from "../shared/icons";

interface Props {
  appKey: string;
  status: string;
  variant?: "icon" | "text";
  confirmStop?: boolean;
}

export function ActionButtons({ appKey, status, variant = "icon", confirmStop = false }: Props) {
  const loading = useRef(signal(false)).current;
  const error = useRef(signal<string | null>(null)).current;
  const showStopConfirm = useRef(signal(false)).current;

  const exec = async (action: (key: string) => Promise<unknown>) => {
    if (loading.value) return;
    error.value = null;
    loading.value = true;
    try {
      await action(appKey);
    } catch (err) {
      error.value =
        err instanceof Error ? err.message : String(err);
    } finally {
      loading.value = false;
    }
  };

  // Clear stale error when app status changes (e.g., WS event arrives after failed action)
  useEffect(() => { error.value = null; }, [status]);

  const canStart = status === "stopped" || status === "failed" || status === "disabled";
  const canStop = status === "running";
  const canReload = status === "running";

  const handleStop = () => {
    if (confirmStop) {
      showStopConfirm.value = true;
    } else {
      void exec(stopApp);
    }
  };

  const isIcon = variant === "icon";
  const btnBase = isIcon ? "ht-btn ht-btn--icon ht-btn--ghost" : "ht-btn ht-btn--sm";

  return (<>
    <div class="ht-btn-group" data-testid="action-buttons">
      {canStart && (
        <button
          class={`${btnBase} ht-btn--success`}
          data-testid={`btn-start-${appKey}`}
          disabled={loading.value}
          onClick={() => void exec(startApp)}
          title={isIcon ? "Start" : undefined}
          aria-label="Start app"
        >
          {isIcon ? <IconPlay /> : <><IconPlay /> Start</>}
        </button>
      )}
      {canReload && (
        <button
          class={`${btnBase}${isIcon ? " ht-btn--info" : ""}`}
          data-testid={`btn-reload-${appKey}`}
          disabled={loading.value}
          onClick={() => void exec(reloadApp)}
          title={isIcon ? "Reload" : undefined}
          aria-label="Reload app"
        >
          {isIcon ? <IconRefresh /> : <><IconRefresh /> Reload</>}
        </button>
      )}
      {canStop && (
        <button
          class={`${btnBase} ${isIcon ? "ht-btn--warning" : "ht-btn--danger"}`}
          data-testid={`btn-stop-${appKey}`}
          disabled={loading.value}
          onClick={handleStop}
          title={isIcon ? "Stop" : undefined}
          aria-label="Stop app"
        >
          {isIcon ? <IconSquare /> : <><IconSquare /> Stop</>}
        </button>
      )}
    </div>
    {confirmStop && showStopConfirm.value && (
      <ConfirmDialog
        title="Stop app?"
        body={`Stop "${appKey}"? It will stop processing events until restarted.`}
        confirmLabel="Stop"
        tone="danger"
        onConfirm={() => {
          showStopConfirm.value = false;
          void exec(stopApp);
        }}
        onCancel={() => { showStopConfirm.value = false; }}
      />
    )}
    {error.value && <p class="ht-text-danger ht-text-sm">{error.value}</p>}
  </>
  );
}
