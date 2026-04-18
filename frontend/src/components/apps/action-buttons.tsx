import { signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import { reloadApp, startApp, stopApp } from "../../api/endpoints";
import { IconPlay, IconRefresh, IconSquare } from "../shared/icons";

interface Props {
  appKey: string;
  status: string;
}

export function ActionButtons({ appKey, status }: Props) {
  const loading = useRef(signal(false)).current;
  const error = useRef(signal<string | null>(null)).current;

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

  return (<>
    <div class="ht-btn-group">
      {canStart && (
        <button
          class="ht-btn ht-btn--icon ht-btn--ghost ht-btn--success"
          data-testid={`btn-start-${appKey}`}
          disabled={loading.value}
          onClick={() => void exec(startApp)}
          title="Start"
          aria-label="Start app"
        >
          <IconPlay />
        </button>
      )}
      {canStop && (
        <button
          class="ht-btn ht-btn--icon ht-btn--ghost ht-btn--warning"
          data-testid={`btn-stop-${appKey}`}
          disabled={loading.value}
          onClick={() => void exec(stopApp)}
          title="Stop"
          aria-label="Stop app"
        >
          <IconSquare />
        </button>
      )}
      {canReload && (
        <button
          class="ht-btn ht-btn--icon ht-btn--ghost ht-btn--info"
          data-testid={`btn-reload-${appKey}`}
          disabled={loading.value}
          onClick={() => void exec(reloadApp)}
          title="Reload"
          aria-label="Reload app"
        >
          <IconRefresh />
        </button>
      )}
    </div>
    {error.value && <p class="ht-text-danger ht-text-sm">{error.value}</p>}
  </>
  );
}
