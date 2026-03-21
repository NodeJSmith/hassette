import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { reloadApp, startApp, stopApp } from "../../api/endpoints";

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
    <div class="ht-action-buttons">
      {canStart && (
        <button
          class="ht-btn ht-btn-sm ht-btn-success"
          disabled={loading.value}
          onClick={() => void exec(startApp)}
        >
          Start
        </button>
      )}
      {canStop && (
        <button
          class="ht-btn ht-btn-sm ht-btn-danger"
          disabled={loading.value}
          onClick={() => void exec(stopApp)}
        >
          Stop
        </button>
      )}
      {canReload && (
        <button
          class="ht-btn ht-btn-sm ht-btn-ghost"
          disabled={loading.value}
          onClick={() => void exec(reloadApp)}
        >
          Reload
        </button>
      )}
    </div>
  );
}
