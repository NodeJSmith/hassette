/**
 * Centralized localStorage utility with consistent key prefixing.
 *
 * All Hassette keys are stored under the "hassette:" prefix.
 * Every read is wrapped in try/catch to handle corrupt data,
 * private browsing mode, and missing localStorage gracefully.
 */

const STORAGE_PREFIX = "hassette:";

/** Read a JSON-serialized Set<string> from localStorage. */
export function getStoredSet(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key);
    if (raw === null) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    const strings = parsed.filter((item): item is string => typeof item === "string");
    return new Set(strings);
  } catch {
    return new Set();
  }
}

/** Write a Set<string> to localStorage as a JSON array. */
export function setStoredSet(key: string, value: Set<string>): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify([...value]));
  } catch {
    // Silently fail (quota exceeded, private browsing, etc.)
  }
}

/**
 * Read a JSON-serialized value from localStorage with a typed fallback.
 *
 * Pass a `validate` guard to verify the parsed value matches the expected
 * type at runtime. Without it, `JSON.parse` is trusted — use only for
 * values you fully control.
 */
export function getStoredValue<T>(
  key: string,
  fallback: T,
  validate?: (v: unknown) => v is T,
): T {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + key);
    if (raw === null) return fallback;
    const parsed: unknown = JSON.parse(raw);
    if (validate && !validate(parsed)) {
      console.warn(`Invalid localStorage value for "${STORAGE_PREFIX}${key}":`, parsed);
      return fallback;
    }
    return parsed as T;
  } catch {
    return fallback;
  }
}

/** Write a JSON-serializable value to localStorage. */
export function setStoredValue<T>(key: string, value: T): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(value));
  } catch {
    // Silently fail (quota exceeded, private browsing, etc.)
  }
}

/**
 * Migrate a legacy localStorage key to the new prefixed scheme.
 *
 * By default (`alreadyJson: false`), wraps the raw value in `JSON.stringify`
 * so it's compatible with `getStoredValue` (which calls `JSON.parse`).
 * Use this for legacy keys that stored plain strings (e.g., `"dark"`).
 *
 * Set `alreadyJson: true` for legacy keys that already stored JSON-encoded
 * values (e.g., `'"dark"'`) — the raw value is written directly.
 *
 * No-op if `oldKey` doesn't exist.
 */
export function migrateKey(oldKey: string, newKey: string, alreadyJson = false): void {
  try {
    const raw = localStorage.getItem(oldKey);
    if (raw === null) return;
    localStorage.setItem(STORAGE_PREFIX + newKey, alreadyJson ? raw : JSON.stringify(raw));
    localStorage.removeItem(oldKey);
  } catch {
    // Silently fail
  }
}
