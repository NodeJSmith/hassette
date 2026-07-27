import path from "node:path";
import preact from "@preact/preset-vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [preact()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    // Zustand's React entry point (`zustand/react`, used by the bare `zustand` import) does
    // `import { useSyncExternalStore } from "react"`. Vitest treats node_modules packages as
    // external SSR deps by default, resolving them via Node's own module resolution — which
    // bypasses the `resolve.alias` mapping "react" -> "preact/compat" that `@preact/preset-vite`
    // sets up. Inlining zustand routes it through Vite's transform pipeline instead, so the
    // alias applies and the hook binds to Preact's `useSyncExternalStore` shim.
    server: {
      deps: {
        inline: [/zustand/],
      },
    },
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/test/**", "src/test-setup.ts", "src/**/*.test.{ts,tsx}"],
      thresholds: {
        statements: 80,
        branches: 80,
        functions: 80,
        lines: 80,
      },
    },
  },
});
