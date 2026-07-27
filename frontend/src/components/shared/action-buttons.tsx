import { useState } from "react";
import { toast } from "sonner";

import { reloadApp, startApp, stopApp } from "../../api/endpoints";
import { useAsyncAction } from "../../hooks/use-async-action";
import styles from "./action-buttons.module.css";
import { Button } from "./button";
import { ConfirmDialog } from "./confirm-dialog";
import { IconPlay, IconRefresh, IconSquare } from "./icons";

// `verb` reads as "Failed to <verb>", `outcome` as "App "<key>" <outcome>".
const ACTIONS = {
  start: { request: startApp, verb: "start", outcome: "started" },
  stop: { request: stopApp, verb: "stop", outcome: "stopped" },
  reload: { request: reloadApp, verb: "reload", outcome: "reloaded" },
} as const;

type ActionName = keyof typeof ACTIONS;

interface Props {
  appKey: string;
  status: string;
  variant?: "icon" | "text";
  confirmStop?: boolean;
}

export function ActionButtons({ appKey, status, variant = "icon", confirmStop = false }: Props) {
  const { loading, run } = useAsyncAction();
  const [showStopConfirm, setShowStopConfirm] = useState(false);

  // The request returns 202 — the toast confirms the action was accepted, the
  // resulting status change arrives later over the WebSocket.
  const exec = (name: ActionName) => {
    const { request, verb, outcome } = ACTIONS[name];
    return run(async () => {
      try {
        await request(appKey);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        toast.error(`Failed to ${verb} "${appKey}": ${message}`);
        throw err;
      }
      toast.success(`App "${appKey}" ${outcome}`);
    });
  };

  const canStart = status === "stopped" || status === "failed" || status === "disabled";
  const canStop = status === "running";
  const canReload = status === "running";

  const handleStop = () => {
    if (confirmStop) {
      setShowStopConfirm(true);
    } else {
      void exec("stop");
    }
  };

  const isIcon = variant === "icon";

  return (
    <>
      <div className={styles.btnGroup} data-role="action-buttons" data-testid="action-buttons">
        {canStart && (
          <Button
            variant="success"
            size={isIcon ? undefined : "sm"}
            ghost={isIcon}
            icon={isIcon}
            data-testid={`btn-start-${appKey}`}
            disabled={loading}
            onClick={() => void exec("start")}
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
            disabled={loading}
            onClick={() => void exec("reload")}
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
            disabled={loading}
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
      {confirmStop && showStopConfirm && (
        <ConfirmDialog
          title="Stop app?"
          body={`Stop "${appKey}"? It will stop processing events until restarted.`}
          confirmLabel="Stop"
          tone="danger"
          onConfirm={() => {
            setShowStopConfirm(false);
            void exec("stop");
          }}
          onCancel={() => {
            setShowStopConfirm(false);
          }}
        />
      )}
    </>
  );
}
