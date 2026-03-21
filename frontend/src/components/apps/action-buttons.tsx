import { signal } from "@preact/signals";
import { useRef } from "preact/hooks";
import { reloadApp, startApp, stopApp } from "../../api/endpoints";

interface Props {
  appKey: string;
  status: string;
}

// Lucide icons
const IconPlay = () => (
  <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <polygon points="6 3 20 12 6 21 6 3" />
  </svg>
);
const IconSquare = () => (
  <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <rect width="14" height="14" x="5" y="5" rx="2" />
  </svg>
);
const IconRefresh = () => (
  <svg class="ht-icon-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
    <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
    <path d="M8 16H3v5" />
  </svg>
);

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
