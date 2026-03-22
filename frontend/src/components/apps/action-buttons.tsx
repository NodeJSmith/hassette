import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { reloadApp, startApp, stopApp } from "../../api/endpoints";
import { IconPlay, IconRefresh, IconSquare } from "../shared/icons";

interface Props {
  appKey: string;
  status: string;
}

export function ActionButtons({ appKey, status }: Props) {
  const loading = useRef(signal(false)).current;

  const exec = async (action: (key: string) => Promise<unknown>) => {
    loading.value = true;
    try {
      await action(appKey);
    } finally {
      loading.value = false;
    }
  };

  const canStart = status === "stopped" || status === "failed";
  const canStop = status === "running";
  const canReload = status === "running";

  return (
    <div class="ht-btn-group">
      {canStart && (
        <button
          class="ht-btn ht-btn--sm ht-btn--success"
          data-testid={`btn-start-${appKey}`}
          disabled={loading.value}
          onClick={() => void exec(startApp)}
        >
          <IconPlay />
          <span>Start</span>
        </button>
      )}
      {canStop && (
        <button
          class="ht-btn ht-btn--sm ht-btn--warning"
          data-testid={`btn-stop-${appKey}`}
          disabled={loading.value}
          onClick={() => void exec(stopApp)}
        >
          <IconSquare />
          <span>Stop</span>
        </button>
      )}
      {canReload && (
        <button
          class="ht-btn ht-btn--sm ht-btn--info"
          data-testid={`btn-reload-${appKey}`}
          disabled={loading.value}
          onClick={() => void exec(reloadApp)}
        >
          <IconRefresh />
          <span>Reload</span>
        </button>
      )}
    </div>
  );
}
