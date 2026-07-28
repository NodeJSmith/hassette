import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiTarget = process.env.VITE_PROXY_TARGET || "http://localhost:8126";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Match tsconfig.json paths["@/*"] so the dev server resolves @/ imports
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
    },
  },
  // Enable SPA history fallback so direct URL access (pasting a deep URL into
  // the browser) serves index.html instead of 404 during development.
  // The /api and /api/ws proxies are unaffected — Vite applies proxy rules
  // before the SPA fallback, so API requests still reach the backend.
  appType: "spa",
  build: {
    outDir: "../src/hassette/web/static/spa",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // WebSocket must come before generic /api to avoid being caught by the prefix match
      "/api/ws": {
        target: apiTarget,
        ws: true,
      },
      "/api": {
        target: apiTarget,
      },
    },
  },
});
