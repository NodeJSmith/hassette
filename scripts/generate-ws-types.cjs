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
export type WsLogPayload = LogEntryResponse;
export type WsExecutionCompletedPayload = ExecutionCompletedData;

// InvocationStatus is also defined in generated-types.ts (from OpenAPI).
// Both are generated from the same Python enum via export_schemas.py --types.
// CI enforces freshness of both files atomically.
`;

const COMPILE_OPTIONS = {
  additionalProperties: false,
  unreachableDefinitions: true,
  bannerComment: "",
  format: true,
};

function preprocessDef(schemaDef) {
  if (!schemaDef || typeof schemaDef !== "object") return;
  if (schemaDef.properties) {
    for (const [, prop] of Object.entries(schemaDef.properties)) {
      if (prop && typeof prop === "object") {
        delete prop.title;
        if (prop.anyOf) {
          for (const variant of prop.anyOf) {
            if (variant && typeof variant === "object") delete variant.title;
          }
        }
        preprocessDef(prop);
      }
    }
    // Use the schema's own required array if present. Only compute from
    // properties when absent — fields with "default" stay optional to match
    // AJV validation and support older servers.
    if (!schemaDef.required) {
      const required = Object.entries(schemaDef.properties)
        .filter(([, prop]) => prop && typeof prop === "object" && !("default" in prop))
        .map(([key]) => key);
      if (required.length > 0) {
        schemaDef.required = required;
      }
    }
  }
  if (schemaDef.items && typeof schemaDef.items === "object") {
    delete schemaDef.items.title;
    preprocessDef(schemaDef.items);
  }
}

async function main() {
  const schema = JSON.parse(fs.readFileSync(SCHEMA_PATH, "utf8"));

  schema.title = "WsServerMessage";

  for (const def of Object.values(schema.$defs || {})) {
    preprocessDef(def);
  }

  const ts = await compile(schema, "WsServerMessage", COMPILE_OPTIONS);

  const output = `${BANNER}\n\n${ts}${COMPAT_ALIASES}`;
  fs.writeFileSync(OUTPUT_PATH, output);
  console.log(`Wrote ${OUTPUT_PATH}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
