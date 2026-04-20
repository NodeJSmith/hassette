const FRAMEWORK_KEY_PREFIX = "__hassette__.";
const FRAMEWORK_KEY_BARE = "__hassette__";

/**
 * Returns true for both bare (`__hassette__`) and prefixed (`__hassette__.<component>`) keys.
 */
export function isFrameworkKey(appKey: string | null | undefined): boolean {
  return appKey !== null && appKey !== undefined && (
    appKey.startsWith(FRAMEWORK_KEY_PREFIX) || appKey === FRAMEWORK_KEY_BARE
  );
}

/**
 * Returns the component slug from a framework key.
 * `__hassette__.service_watcher` → `service_watcher`
 * `__hassette__` → `framework` (legacy bare-key path — new telemetry rows use prefixed keys)
 */
export function frameworkDisplayName(appKey: string): string {
  if (appKey === FRAMEWORK_KEY_BARE) return "framework";
  return appKey.startsWith(FRAMEWORK_KEY_PREFIX)
    ? appKey.slice(FRAMEWORK_KEY_PREFIX.length)
    : appKey;
}

/**
 * Returns a human-readable label for a framework key.
 * `__hassette__.service_watcher` → `Service Watcher`
 * `__hassette__.ServiceWatcher` → `Service Watcher`
 * `__hassette__` → `Framework`
 */
export function frameworkDisplayLabel(appKey: string): string {
  const slug = frameworkDisplayName(appKey);
  const words = slug.replace(/([a-z])([A-Z])/g, "$1 $2").split(/[_ ]+/).filter((w) => w.length > 0);
  return words.map((w) => w[0].toUpperCase() + w.slice(1).toLowerCase()).join(" ");
}
