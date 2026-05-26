#!/usr/bin/env node
/**
 * Generate ws-types.ts from ws-schema.json using json-schema-to-typescript.
 *
 * Pydantic v2 adds "title" to every property in its JSON Schema output, which
 * causes json-schema-to-typescript to emit a standalone `export type X = string`
 * alias for each field. This script strips property-level titles before codegen
 * to produce clean, readable interfaces.
 *
 * Usage: node scripts/generate-ws-types.cjs
 */

const fs = require("fs");
const path = require("path");

const FRONTEND_DIR = path.resolve(__dirname, "..", "frontend");

// Resolve from frontend's node_modules
const { compile } = require(
  require.resolve("json-schema-to-typescript", { paths: [FRONTEND_DIR] }),
);

const SCHEMA_PATH = path.join(FRONTEND_DIR, "ws-schema.json");
const OUTPUT_PATH = path.join(FRONTEND_DIR, "src", "api", "ws-types.ts");

const BANNER = `/* @generated from ws-schema.json — do not edit by hand.
 * Regenerate: node scripts/generate-ws-types.cjs
 * Or: uv run python scripts/export_schemas.py --types
 */`;

const COMPAT_ALIASES = `
// Backward-compatible aliases for consumers that use the Ws*Payload naming
export type WsLogPayload = LogEntryResponse;
export type WsInvocationCompletedPayload = InvocationCompletedData;
export type WsExecutionCompletedPayload = ExecutionCompletedData;

// Note: InvocationStatus is also defined in generated-types.ts (from OpenAPI).
// Both are generated from the same Python enum via export_schemas.py --types.
// CI enforces freshness of both files atomically.
`;

function preprocessDef(obj) {
  if (!obj || typeof obj !== "object") return;
  if (obj.properties) {
    for (const [key, prop] of Object.entries(obj.properties)) {
      if (prop && typeof prop === "object") {
        // Strip property-level titles (they cause noisy type aliases)
        delete prop.title;
        if (prop.anyOf) {
          for (const variant of prop.anyOf) {
            if (variant && typeof variant === "object") delete variant.title;
          }
        }
        // Recurse into nested schemas (inline objects, items)
        preprocessDef(prop);
      }
    }
    // Use the schema's own required array if present (Pydantic generates correct
    // ones). Only compute from properties when absent — fields with "default"
    // stay optional to match AJV validation and support older servers.
    if (!obj.required) {
      const required = Object.entries(obj.properties)
        .filter(([, prop]) => prop && typeof prop === "object" && !("default" in prop))
        .map(([key]) => key);
      if (required.length > 0) {
        obj.required = required;
      }
    }
  }
  if (obj.items && typeof obj.items === "object") {
    delete obj.items.title;
    preprocessDef(obj.items);
  }
}

async function main() {
  const schema = JSON.parse(fs.readFileSync(SCHEMA_PATH, "utf8"));

  schema.title = "WsServerMessage";

  for (const def of Object.values(schema.$defs || {})) {
    preprocessDef(def);
  }

  const ts = await compile(schema, "WsServerMessage", {
    additionalProperties: false,
    unreachableDefinitions: true,
    bannerComment: "",
    format: true,
  });

  const output = `${BANNER}\n\n${ts}${COMPAT_ALIASES}`;
  fs.writeFileSync(OUTPUT_PATH, output);
  console.log(`Wrote ${OUTPUT_PATH}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
