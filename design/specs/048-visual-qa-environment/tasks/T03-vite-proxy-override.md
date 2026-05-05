---
task_id: "T03"
title: "Add env var override for Vite proxy target"
status: "done"
depends_on: []
implements: ["FR#5", "AC#7"]
---

## Summary
Modify `frontend/vite.config.ts` to read the API proxy target from an environment variable (`VITE_PROXY_TARGET`) instead of hardcoding `http://localhost:8126`. The default value remains unchanged so existing development workflows are unaffected. This enables the demo orchestrator to point Vite at a dynamically allocated hassette backend port.

## Prompt
Edit `frontend/vite.config.ts`. Currently the proxy config is:

```typescript
server: {
  proxy: {
    "/api/ws": {
      target: "http://localhost:8126",
      ws: true,
    },
    "/api": {
      target: "http://localhost:8126",
    },
  },
},
```

Change it to read from `process.env.VITE_PROXY_TARGET`:

```typescript
const apiTarget = process.env.VITE_PROXY_TARGET || "http://localhost:8126";

// ... in defineConfig:
server: {
  proxy: {
    "/api/ws": {
      target: apiTarget,
      ws: true,
    },
    "/api": {
      target: apiTarget,
    },
  },
},
```

The variable is declared outside `defineConfig` so it's evaluated once at server startup. The `|| "http://localhost:8126"` fallback ensures the default behavior is identical when `VITE_PROXY_TARGET` is not set.

## Focus
- This is a backward-compatible change. When `VITE_PROXY_TARGET` is not set, the behavior is identical to today.
- Vite's `process.env` is available in `vite.config.ts` (it's a Node.js file, not browser code). No special Vite env prefix (`VITE_`) is needed for config-level access — the `VITE_` prefix convention only applies to client-side env vars exposed via `import.meta.env`.
- The WebSocket proxy (`/api/ws`) must use the same target as the REST proxy (`/api`). Both use the same variable.

## Verify
- [ ] FR#5: `frontend/vite.config.ts` reads proxy target from `process.env.VITE_PROXY_TARGET` with `http://localhost:8126` as default, applied to both `/api/ws` and `/api` proxy entries
- [ ] AC#7: When `VITE_PROXY_TARGET` is not set, the proxy target is `http://localhost:8126` (unchanged default behavior)
