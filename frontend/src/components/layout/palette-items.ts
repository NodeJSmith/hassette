import type { AppManifest, ListenerData } from "../../api/endpoints";
import { reloadApp, stopApp } from "../../api/endpoints";
import type { components } from "../../api/generated-types";
import type { AppStatusEntry } from "../../state/store";
import { appLiveStatus, instanceLiveStatus } from "../../utils/app-data";
import { appDetailPath, handlerPath, NAV_PAGES } from "../../utils/app-routes";
import { isFailureStatus, isReloadableStatus } from "../../utils/status";

type ManifestStatus = components["schemas"]["ManifestStatus"];
type ResourceStatus = components["schemas"]["ResourceStatus"];

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
  status?: ManifestStatus | ResourceStatus;
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

/** Removed apps (in_current_config: false) are historical/DB-only — the runtime doesn't know
 * about them, so they're excluded from every actionable palette result (stop/reload would 404
 * or no-op, and "jump to…" is for apps a user can actually act on). */
function activeManifests(manifests: AppManifest[]): AppManifest[] {
  return manifests.filter((m) => m.in_current_config);
}

export function buildActionItems(
  manifests: AppManifest[],
  appStatuses: Record<string, AppStatusEntry>,
  onClose: () => void,
): PaletteItem[] {
  const active = activeManifests(manifests);
  return [
    {
      id: "action-reload-all",
      kind: "action",
      label: "Reload all apps",
      action: () => {
        // Live status, not m.status — see appLiveStatus for why the cached manifest can be stale.
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
        // stop (any failure status), not "is stop meaningful for this app" (which running is too).
        const failing = active.filter((m) => isFailureStatus(appLiveStatus(appStatuses, m)));
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
  const sorted = activeManifests(manifests).sort((a, b) => a.app_key.localeCompare(b.app_key));
  for (const m of sorted) {
    items.push({
      id: `app-${m.app_key}`,
      kind: "app",
      label: m.display_name,
      sub: m.app_key,
      // Live overlay here and on the instance rows below, not m.status — see appLiveStatus for
      // why the cached manifest can be stale.
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
