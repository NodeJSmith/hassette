import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Tests for localStorage utility with hassette: prefix.
 *
 * Uses a real Map-backed mock of localStorage to test serialization,
 * error handling, and key migration.
 */

// Lazy import so the module under test can be loaded after mocks are set up.
let mod: typeof import("./local-storage");

function createMockStorage(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: vi.fn((key: string) => store.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      store.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      store.delete(key);
    }),
    clear: vi.fn(() => {
      store.clear();
    }),
    get length() {
      return store.size;
    },
    key: vi.fn((index: number) => [...store.keys()][index] ?? null),
  };
}

let mockStorage: Storage;

beforeEach(async () => {
  mockStorage = createMockStorage();
  Object.defineProperty(globalThis, "localStorage", {
    value: mockStorage,
    writable: true,
    configurable: true,
  });
  // Re-import to get a fresh module (no stale closure over old localStorage)
  mod = await import("./local-storage");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("getStoredValue", () => {
  it("returns fallback for missing key", () => {
    expect(mod.getStoredValue("missing", 42)).toBe(42);
  });

  it("returns stored string value", () => {
    mockStorage.setItem("hassette:theme", JSON.stringify("dark"));
    expect(mod.getStoredValue("theme", "light")).toBe("dark");
  });

  it("returns fallback for corrupt JSON", () => {
    mockStorage.setItem("hassette:bad", "{broken");
    expect(mod.getStoredValue("bad", "fallback")).toBe("fallback");
  });
});

describe("getStoredValue with validator", () => {
  const isTheme = (v: unknown): v is "dark" | "light" => typeof v === "string" && ["dark", "light"].includes(v);

  it("returns valid value when validator passes", () => {
    mockStorage.setItem("hassette:theme", JSON.stringify("light"));
    expect(mod.getStoredValue("theme", "dark", isTheme)).toBe("light");
  });

  it("returns fallback when validator rejects", () => {
    mockStorage.setItem("hassette:theme", JSON.stringify("blue"));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(mod.getStoredValue("theme", "dark", isTheme)).toBe("dark");
    expect(warnSpy).toHaveBeenCalledOnce();
    warnSpy.mockRestore();
  });

  it("returns fallback when stored type is wrong", () => {
    mockStorage.setItem("hassette:theme", JSON.stringify(42));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(mod.getStoredValue("theme", "dark", isTheme)).toBe("dark");
    expect(warnSpy).toHaveBeenCalledOnce();
    warnSpy.mockRestore();
  });
});

describe("setStoredValue / getStoredValue roundtrip", () => {
  it("roundtrips a string", () => {
    mod.setStoredValue("color", "blue");
    expect(mod.getStoredValue("color", "red")).toBe("blue");
  });

  it("roundtrips a number", () => {
    mod.setStoredValue("count", 7);
    expect(mod.getStoredValue("count", 0)).toBe(7);
  });

  it("roundtrips a boolean", () => {
    mod.setStoredValue("flag", true);
    expect(mod.getStoredValue("flag", false)).toBe(true);
  });
});

describe("migrateKey", () => {
  it("moves value from old key to new prefixed key (JSON-encoded) and deletes old", () => {
    mockStorage.setItem("ht-theme", "light");
    mod.migrateKey("ht-theme", "theme");

    // New key has the JSON-encoded value (compatible with getStoredValue)
    expect(mockStorage.getItem("hassette:theme")).toBe(JSON.stringify("light"));
    // Old key is deleted
    expect(mockStorage.getItem("ht-theme")).toBeNull();
    // Roundtrip via getStoredValue works
    expect(mod.getStoredValue("theme", "dark")).toBe("light");
  });

  it("is a no-op when old key does not exist", () => {
    mod.migrateKey("nonexistent", "target");
    expect(mockStorage.getItem("hassette:target")).toBeNull();
    expect(mockStorage.removeItem).not.toHaveBeenCalled();
  });
});

describe("setStoredValue silently fails when localStorage throws", () => {
  it("does not throw when setItem throws", () => {
    vi.spyOn(mockStorage, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    expect(() => mod.setStoredValue("key", "val")).not.toThrow();
  });
});
