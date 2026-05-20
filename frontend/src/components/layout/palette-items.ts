import { reloadApp, stopApp } from "../../api/endpoints";
import type { AppManifest, ListenerData } from "../../api/endpoints";
import { formatListenerId } from "../../utils/handler-ids";

export type PaletteItemKind = "page" | "app" | "instance" | "handler" | "action";

export interface PaletteItem {
  id: string;
  kind: PaletteItemKind;
  label: string;
  sub?: string;
  status?: string;
  action: () => void;
}

export function buildStaticPageItems(navigate: (path: string) => void): PaletteItem[] {
  return [
    {
      id: "page-apps",
      kind: "page",
      label: "apps",
      sub: "/apps",
      action: () => navigate("/apps"),
    },
    {
      id: "page-handlers",
      kind: "page",
      label: "handlers",
      sub: "/handlers",
      action: () => navigate("/handlers"),
    },
    {
      id: "page-logs",
      kind: "page",
      label: "logs",
      sub: "/logs",
      action: () => navigate("/logs"),
    },
    {
      id: "page-config",
      kind: "page",
      label: "config",
      sub: "/config",
      action: () => navigate("/config"),
    },
  ];
}

export function buildActionItems(
  manifests: AppManifest[],
  onClose: () => void,
): PaletteItem[] {
  return [
    {
      id: "action-reload-all",
      kind: "action",
      label: "Reload all apps",
      action: () => {
        const running = manifests.filter((m) => m.status === "running");
        void Promise.allSettled(running.map((m) => reloadApp(m.app_key)));
        onClose();
      },
    },
    {
      id: "action-stop-failing",
      kind: "action",
      label: "Stop all failing",
      action: () => {
        const failing = manifests.filter((m) => m.status === "failed" || m.status === "crashed");
        void Promise.allSettled(failing.map((m) => stopApp(m.app_key)));
        onClose();
      },
    },
    {
      id: "action-open-docs",
      kind: "action",
      label: "Open docs",
      action: () => {
        window.open("https://hassette.readthedocs.io", "_blank", "noreferrer");
        onClose();
      },
    },
  ];
}

export function buildAppItems(manifests: AppManifest[], navigate: (path: string) => void, onClose: () => void): PaletteItem[] {
  const items: PaletteItem[] = [];
  const sorted = [...manifests].sort((a, b) => a.app_key.localeCompare(b.app_key));
  for (const m of sorted) {
    items.push({
      id: `app-${m.app_key}`,
      kind: "app",
      label: m.display_name,
      sub: m.app_key,
      status: m.status,
      action: () => {
        navigate(`/apps/${m.app_key}`);
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
          status: inst.status,
          action: () => {
            navigate(`/apps/${m.app_key}?instance=${inst.index}`);
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
      navigate(`/apps/${l.app_key}/handlers/${formatListenerId(l.listener_id)}`);
      onClose();
    },
  }));
}

export function matchesQuery(item: PaletteItem, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  if (item.label.toLowerCase().includes(q)) return true;
  if (item.sub?.toLowerCase().includes(q)) return true;
  if (item.kind.toLowerCase().includes(q)) return true;
  return false;
}
