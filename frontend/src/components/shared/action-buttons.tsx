import { useEffect } from "preact/hooks";

import { reloadApp, startApp, stopApp } from "../../api/endpoints";
import { useAsyncAction } from "../../hooks/use-async-action";
import { useSignal } from "../../hooks/use-signal";
import styles from "./action-buttons.module.css";
import { Button } from "./button";
import { ConfirmDialog } from "./confirm-dialog";
import { IconPlay, IconRefresh, IconSquare } from "./icons";

interface Props {
  appKey: string;
  status: string;
  variant?: "icon" | "text";
  confirmStop?: boolean;
}

export function ActionButtons({ appKey, status, variant = "icon", confirmStop = false }: Props) {
  const { loading, error, run } = useAsyncAction();
  const showStopConfirm = useSignal(false);

  const exec = (action: (key: string) => Promise<unknown>) => run(() => action(appKey));

  // Clear stale error when app status changes (e.g., WS event arrives after failed action)
  useEffect(() => {
    error.value = null;
  }, [status]);

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

  return (
    <>
      <div class={styles.btnGroup} data-role="action-buttons" data-testid="action-buttons">
        {canStart && (
          <Button
            variant="success"
            size={isIcon ? undefined : "sm"}
            ghost={isIcon}
            icon={isIcon}
            data-testid={`btn-start-${appKey}`}
            disabled={loading.value}
            onClick={() => void exec(startApp)}
            title={isIcon ? "Start" : undefined}
            aria-label="Start app"
          >
            {isIcon ? (
              <IconPlay />
            ) : (
              <>
                <IconPlay /> Start
              </>
            )}
          </Button>
        )}
        {canReload && (
          <Button
            variant={isIcon ? "info" : undefined}
            size={isIcon ? undefined : "sm"}
            ghost={isIcon}
            icon={isIcon}
            data-testid={`btn-reload-${appKey}`}
            disabled={loading.value}
            onClick={() => void exec(reloadApp)}
            title={isIcon ? "Reload" : undefined}
            aria-label="Reload app"
          >
            {isIcon ? (
              <IconRefresh />
            ) : (
              <>
                <IconRefresh /> Reload
              </>
            )}
          </Button>
        )}
        {canStop && (
          <Button
            variant={isIcon ? "warning" : "danger"}
            size={isIcon ? undefined : "sm"}
            ghost={isIcon}
            icon={isIcon}
            data-testid={`btn-stop-${appKey}`}
            disabled={loading.value}
            onClick={handleStop}
            title={isIcon ? "Stop" : undefined}
            aria-label="Stop app"
          >
            {isIcon ? (
              <IconSquare />
            ) : (
              <>
                <IconSquare /> Stop
              </>
            )}
          </Button>
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
          onCancel={() => {
            showStopConfirm.value = false;
          }}
        />
      )}
      {error.value && (
        <p class="ht-text-danger ht-text-sm" role="alert" data-testid="action-buttons-error">
          {error.value}
        </p>
      )}
    </>
  );
}
