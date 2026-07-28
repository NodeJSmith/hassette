import type { ComponentProps, ReactNode } from "react";
import { useState } from "react";
import { toast } from "sonner";

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

import { reloadApp, startApp, stopApp } from "../../api/endpoints";
import { useAsyncAction } from "../../hooks/use-async-action";
import styles from "./action-buttons.module.css";
import { IconPlay, IconRefresh, IconSquare } from "./icons";

// `verb` reads as "Failed to <verb>", `outcome` as "App "<key>" <outcome>".
const ACTIONS = {
  start: { request: startApp, verb: "start", outcome: "started" },
  stop: { request: stopApp, verb: "stop", outcome: "stopped" },
  reload: { request: reloadApp, verb: "reload", outcome: "reloaded" },
} as const;

type ActionName = keyof typeof ACTIONS;
type ButtonVariant = ComponentProps<typeof Button>["variant"];

interface ActionButtonSpec {
  action: ActionName;
  visible: boolean;
  iconVariant: ButtonVariant;
  textVariant: ButtonVariant;
  icon: ReactNode;
  label: string;
  ariaLabel: string;
  onClick: () => void;
}

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

  const buttons: ActionButtonSpec[] = [
    {
      action: "start",
      visible: canStart,
      iconVariant: "success-ghost",
      textVariant: "success",
      icon: <IconPlay />,
      label: "Start",
      ariaLabel: "Start app",
      onClick: () => void exec("start"),
    },
    {
      action: "reload",
      visible: canReload,
      iconVariant: "info-ghost",
      textVariant: "outline",
      icon: <IconRefresh />,
      label: "Reload",
      ariaLabel: "Reload app",
      onClick: () => void exec("reload"),
    },
    {
      action: "stop",
      visible: canStop,
      iconVariant: "warning-ghost",
      textVariant: "danger",
      icon: <IconSquare />,
      label: "Stop",
      ariaLabel: "Stop app",
      onClick: handleStop,
    },
  ];

  return (
    <>
      <div className={styles.btnGroup} data-role="action-buttons" data-testid="action-buttons">
        {buttons.map(
          (btn) =>
            btn.visible && (
              <Button
                key={btn.action}
                variant={isIcon ? btn.iconVariant : btn.textVariant}
                size={isIcon ? "icon" : "sm"}
                data-testid={`btn-${btn.action}-${appKey}`}
                disabled={loading}
                onClick={btn.onClick}
                title={isIcon ? btn.label : undefined}
                aria-label={btn.ariaLabel}
              >
                {isIcon ? (
                  btn.icon
                ) : (
                  <>
                    {btn.icon} {btn.label}
                  </>
                )}
              </Button>
            ),
        )}
      </div>
      {confirmStop && (
        <AlertDialog open={showStopConfirm} onOpenChange={setShowStopConfirm}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Stop app?</AlertDialogTitle>
              <AlertDialogDescription>
                Stop &quot;{appKey}&quot;? It will stop processing events until restarted.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                data-testid="confirm-btn-danger"
                onClick={() => {
                  void exec("stop");
                }}
              >
                Stop
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </>
  );
}
