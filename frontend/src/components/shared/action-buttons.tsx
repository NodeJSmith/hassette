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

import { reloadApp, reloadInstance, startApp, startInstance, stopApp, stopInstance } from "../../api/endpoints";
import { useAsyncAction } from "../../hooks/use-async-action";
import type { ActionButtonStatusKey } from "../../utils/status";
import { CAN_START, CAN_STOP, isReloadableStatus } from "../../utils/status";
import { IconPlay, IconRefresh, IconSquare } from "./icons";

// `verb` reads as "Failed to <verb>", `outcome` as "App "<key>" <outcome>".
const ACTIONS = {
  start: { request: startApp, instanceRequest: startInstance, verb: "start", outcome: "started" },
  stop: { request: stopApp, instanceRequest: stopInstance, verb: "stop", outcome: "stopped" },
  reload: { request: reloadApp, instanceRequest: reloadInstance, verb: "reload", outcome: "reloaded" },
} as const;

type ActionName = keyof typeof ACTIONS;
type ButtonVariant = ComponentProps<typeof Button>["variant"];

interface InstanceRef {
  index: number;
  name: string;
}

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
async function performAction(appKey: string, name: ActionName, instance?: InstanceRef) {
  const { request, instanceRequest, verb, outcome } = ACTIONS[name];
  try {
    if (instance) {
      await instanceRequest(appKey, instance.index);
    } else {
      await request(appKey);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    if (instance) {
      toast.error(`Failed to ${verb} instance "${instance.name}" of "${appKey}": ${message}`);
    } else {
      toast.error(`Failed to ${verb} "${appKey}": ${message}`);
    }
    throw err;
  }
  if (instance) {
    toast.success(`Instance "${instance.name}" of "${appKey}" ${outcome}`);
  } else {
    toast.success(`App "${appKey}" ${outcome}`);
  }
}

function buildButtonSpecs(
  status: ActionButtonStatusKey,
  handlers: Record<ActionName, () => void>,
  instance?: InstanceRef,
): ActionButtonSpec[] {
  return [
    {
      action: "start",
      visible: CAN_START[status],
      iconVariant: "success-ghost",
      textVariant: "success",
      icon: <IconPlay />,
      label: "Start",
      ariaLabel: instance ? `Start instance '${instance.name}'` : "Start app",
      onClick: handlers.start,
    },
    {
      action: "reload",
      visible: status !== "unknown" && isReloadableStatus(status),
      iconVariant: "info-ghost",
      textVariant: "outline",
      icon: <IconRefresh />,
      label: "Reload",
      ariaLabel: instance ? `Reload instance '${instance.name}'` : "Reload app",
      onClick: handlers.reload,
    },
    {
      action: "stop",
      visible: CAN_STOP[status],
      iconVariant: "warning-ghost",
      textVariant: "danger",
      icon: <IconSquare />,
      label: "Stop",
      ariaLabel: instance ? `Stop instance '${instance.name}'` : "Stop app",
      onClick: handlers.stop,
    },
  ];
}

interface ActionButtonProps {
  spec: ActionButtonSpec;
  appKey: string;
  isIcon: boolean;
  disabled: boolean;
  instance?: InstanceRef;
}

function ActionButton({ spec, appKey, isIcon, disabled, instance }: ActionButtonProps) {
  const testId = instance ? `btn-${spec.action}-${appKey}-${instance.index}` : `btn-${spec.action}-${appKey}`;
  return (
    <Button
      variant={isIcon ? spec.iconVariant : spec.textVariant}
      size={isIcon ? "icon" : "sm"}
      data-testid={testId}
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
  instanceName?: string;
}

function StopConfirmDialog({ appKey, open, onOpenChange, onConfirm, instanceName }: StopConfirmDialogProps) {
  const title = instanceName ? `Stop instance '${instanceName}'?` : "Stop app?";
  const description = instanceName ? (
    `Stop instance '${instanceName}' of '${appKey}'? It will stop processing events until restarted.`
  ) : (
    <>Stop &quot;{appKey}&quot;? It will stop processing events until restarted.</>
  );
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
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
  instance?: InstanceRef;
}

export function ActionButtons({ appKey, status, variant = "icon", confirmStop = false, instance }: Props) {
  const { loading, run } = useAsyncAction();
  const [showStopConfirm, setShowStopConfirm] = useState(false);

  const exec = (name: ActionName) => run(() => performAction(appKey, name, instance));

  const handleStop = () => {
    if (confirmStop) {
      setShowStopConfirm(true);
    } else {
      void exec("stop");
    }
  };

  const isIcon = variant === "icon";
  const buttons = buildButtonSpecs(
    status,
    {
      start: () => void exec("start"),
      reload: () => void exec("reload"),
      stop: handleStop,
    },
    instance,
  );

  return (
    <>
      <div className="flex flex-nowrap gap-1" data-role="action-buttons" data-testid="action-buttons">
        {buttons.map(
          (btn) =>
            btn.visible && (
              <ActionButton
                key={btn.action}
                spec={btn}
                appKey={appKey}
                isIcon={isIcon}
                disabled={loading}
                instance={instance}
              />
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
          instanceName={instance?.name}
        />
      )}
    </>
  );
}
