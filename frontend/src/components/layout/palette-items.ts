import type { AppManifest, ListenerData } from "../../api/endpoints";
import { reloadApp, stopApp } from "../../api/endpoints";
import type { AppStatusEntry } from "../../state/store";
import { appLiveStatus, instanceLiveStatus } from "../../utils/app-data";
import { appDetailPath, handlerPath, NAV_PAGES } from "../../utils/app-routes";
import { isReloadableStatus } from "../../utils/status";

const DOCS_URL = "https://hassette.readthedocs.io";

export type PaletteItemKind = "page" | "app" | "instance" | "handler" | "action";

export const KIND_ORDER: PaletteItemKind[] = ["page", "app", "instance", "handler", "action"];

export const KIND_LABEL: Record<PaletteItemKind, string> = {
  page: "pages",
  app: "apps",
  instance: "instances",
  handler: "handlers",
  action: "actions",
};

export interface PaletteItem {
  id: string;
  kind: PaletteItemKind;
  label: string;
  sub?: string;
  status?: string;
  action: () => void;
}

export function buildStaticPageItems(navigate: (path: string) => void): PaletteItem[] {
  return NAV_PAGES.map((page) => ({
    id: `page-${page.label}`,
    kind: "page" as const,
    label: page.label,
    sub: page.path,
    action: () => navigate(page.path),
  }));
}

export function buildActionItems(
  manifests: AppManifest[],
  appStatuses: Record<string, AppStatusEntry>,
  onClose: () => void,
): PaletteItem[] {
  // Removed apps (in_current_config: false) aren't loaded — stop/reload would 404 or no-op
  // against an app the runtime doesn't know about, so exclude them the same way buildAppItems does.
  const active = manifests.filter((m) => m.in_current_config);
  return [
    {
      id: "action-reload-all",
      kind: "action",
      label: "Reload all apps",
      action: () => {
        // Selection is derived from live per-instance WS status, not the cached manifest's
        // m.status — app_status_changed updates only the Zustand status map and does not
        // invalidate useManifests(), so a manifest can go stale (e.g. still "running" after an
        // instance fails) for as long as no execution event happens to refetch the palette data.
        const reloadable = active.filter((m) => isReloadableStatus(appLiveStatus(appStatuses, m)));
        void Promise.allSettled(reloadable.map((m) => reloadApp(m.app_key)));
        onClose();
      },
    },
    {
      id: "action-stop-failing",
      kind: "action",
      label: "Stop all failing",
      action: () => {
        // Not isReloadableStatus's stop-side counterpart — this targets apps recovery should
        // stop (failed/degraded), not "is stop meaningful for this app" (which running is too).
        // Same live-status derivation as reload-all above, for the same reason.
        const failing = active.filter((m) => {
          const live = appLiveStatus(appStatuses, m);
          return live === "failed" || live === "degraded";
        });
        void Promise.allSettled(failing.map((m) => stopApp(m.app_key)));
        onClose();
      },
    },
    {
      id: "action-open-docs",
      kind: "action",
      label: "Open docs",
      action: () => {
        window.open(DOCS_URL, "_blank", "noreferrer");
        onClose();
      },
    },
  ];
}

export function buildAppItems(
  manifests: AppManifest[],
  appStatuses: Record<string, AppStatusEntry>,
  navigate: (path: string) => void,
  onClose: () => void,
): PaletteItem[] {
  const items: PaletteItem[] = [];
  // Removed apps (in_current_config: false) are historical/DB-only — excluded from "jump
  // to…" results, which are for navigating to apps a user can actually act on.
  const sorted = [...manifests].filter((m) => m.in_current_config).sort((a, b) => a.app_key.localeCompare(b.app_key));
  for (const m of sorted) {
    items.push({
      id: `app-${m.app_key}`,
      kind: "app",
      label: m.display_name,
      sub: m.app_key,
      // Live overlay, not m.status directly — same staleness reasoning as buildActionItems above.
      status: appLiveStatus(appStatuses, m),
      action: () => {
        navigate(appDetailPath(m.app_key));
        onClose();
      },
    });
    if (m.instance_count > 1) {
      for (const inst of m.instances ?? []) {
        items.push({
          id: `instance-${m.app_key}-${inst.index}`,
          kind: "instance",
          label: inst.instance_name,
          sub: `${m.app_key} · #${inst.index}`,
          // Live overlay for this one instance — same reasoning as the app row above.
          status: instanceLiveStatus(appStatuses, m.app_key, inst),
          action: () => {
            navigate(appDetailPath(m.app_key, undefined, { instance: inst.index }));
            onClose();
          },
        });
      }
    }
  }
  return items;
}

export function buildHandlerItems(
  listeners: ListenerData[],
  navigate: (path: string) => void,
  onClose: () => void,
): PaletteItem[] {
  return listeners.map((l) => ({
    id: `handler-${l.listener_id}`,
    kind: "handler" as const,
    label: l.handler_method,
    sub: `${l.app_key} · ${l.topic}`,
    action: () => {
      navigate(handlerPath(l.app_key, "listener", l.listener_id));
      onClose();
    },
  }));
}
