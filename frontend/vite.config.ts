import preact from "@preact/preset-vite";
import { defineConfig } from "vite";

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
        target: "http://localhost:8126",
        ws: true,
      },
      "/api": {
        target: "http://localhost:8126",
      },
    },
  },
});
