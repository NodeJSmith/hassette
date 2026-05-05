import preact from "@preact/preset-vite";
import { defineConfig } from "vite";

const apiTarget = process.env.VITE_PROXY_TARGET || "http://localhost:8126";

export default defineConfig({
  plugins: [preact()],
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
