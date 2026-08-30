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
import type { ActionButtonStatusKey } from "../../utils/status";
import { CAN_START, CAN_STOP, isReloadableStatus } from "../../utils/status";
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

// The request returns 202 — the toast confirms the action was accepted, the
// resulting status change arrives later over the WebSocket.
async function performAction(appKey: string, name: ActionName) {
  const { request, verb, outcome } = ACTIONS[name];
  try {
    await request(appKey);
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    toast.error(`Failed to ${verb} "${appKey}": ${message}`);
    throw err;
  }
  toast.success(`App "${appKey}" ${outcome}`);
}

function buildButtonSpecs(status: ActionButtonStatusKey, handlers: Record<ActionName, () => void>): ActionButtonSpec[] {
  return [
    {
      action: "start",
      visible: CAN_START[status],
      iconVariant: "success-ghost",
      textVariant: "success",
      icon: <IconPlay />,
      label: "Start",
      ariaLabel: "Start app",
      onClick: handlers.start,
    },
    {
      action: "reload",
      visible: status !== "unknown" && isReloadableStatus(status),
      iconVariant: "info-ghost",
      textVariant: "outline",
      icon: <IconRefresh />,
      label: "Reload",
      ariaLabel: "Reload app",
      onClick: handlers.reload,
    },
    {
      action: "stop",
      visible: CAN_STOP[status],
      iconVariant: "warning-ghost",
      textVariant: "danger",
      icon: <IconSquare />,
      label: "Stop",
      ariaLabel: "Stop app",
      onClick: handlers.stop,
    },
  ];
}

interface ActionButtonProps {
  spec: ActionButtonSpec;
  appKey: string;
  isIcon: boolean;
  disabled: boolean;
}

function ActionButton({ spec, appKey, isIcon, disabled }: ActionButtonProps) {
  return (
    <Button
      variant={isIcon ? spec.iconVariant : spec.textVariant}
      size={isIcon ? "icon" : "sm"}
      data-testid={`btn-${spec.action}-${appKey}`}
      disabled={disabled}
      onClick={spec.onClick}
      title={isIcon ? spec.label : undefined}
      aria-label={spec.ariaLabel}
    >
      {isIcon ? (
        spec.icon
      ) : (
        <>
          {spec.icon} {spec.label}
        </>
      )}
    </Button>
  );
}

interface StopConfirmDialogProps {
  appKey: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}

function StopConfirmDialog({ appKey, open, onOpenChange, onConfirm }: StopConfirmDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Stop app?</AlertDialogTitle>
          <AlertDialogDescription>
            Stop &quot;{appKey}&quot;? It will stop processing events until restarted.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction variant="destructive" data-testid="confirm-btn-danger" onClick={onConfirm}>
            Stop
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

interface Props {
  appKey: string;
  // `unknown` is a defensive placeholder the app-detail page passes while a status hasn't
  // loaded yet (see `AppDetailPage`'s `liveStatus` selector) — not a backend enum value.
  status: ActionButtonStatusKey;
  variant?: "icon" | "text";
  confirmStop?: boolean;
}

export function ActionButtons({ appKey, status, variant = "icon", confirmStop = false }: Props) {
  const { loading, run } = useAsyncAction();
  const [showStopConfirm, setShowStopConfirm] = useState(false);

  const exec = (name: ActionName) => run(() => performAction(appKey, name));

  const handleStop = () => {
    if (confirmStop) {
      setShowStopConfirm(true);
    } else {
      void exec("stop");
    }
  };

  const isIcon = variant === "icon";
  const buttons = buildButtonSpecs(status, {
    start: () => void exec("start"),
    reload: () => void exec("reload"),
    stop: handleStop,
  });

  return (
    <>
      <div className="flex flex-nowrap gap-1" data-role="action-buttons" data-testid="action-buttons">
        {buttons.map(
          (btn) =>
            btn.visible && (
              <ActionButton key={btn.action} spec={btn} appKey={appKey} isIcon={isIcon} disabled={loading} />
            ),
        )}
      </div>
      {confirmStop && (
        <StopConfirmDialog
          appKey={appKey}
          open={showStopConfirm}
          onOpenChange={setShowStopConfirm}
          onConfirm={() => {
            void exec("stop");
          }}
        />
      )}
    </>
  );
}
