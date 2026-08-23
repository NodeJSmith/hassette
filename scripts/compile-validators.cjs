#!/usr/bin/env node
/**
 * Precompile ws-schema.json into a standalone AJV validation function.
 *
 * The generated file replaces runtime `new Ajv().compile()` in ws-validator.ts,
 * removing the full Ajv compiler from the production bundle. Only ajv/dist/runtime
 * helpers remain.
 *
 * Usage: node scripts/compile-validators.cjs
 */

const fs = require("fs");
const path = require("path");

const FRONTEND_DIR = path.resolve(__dirname, "..", "frontend");

// Resolve from frontend's node_modules
const Ajv = require(require.resolve("ajv", { paths: [FRONTEND_DIR] }));
const standaloneCode = require(
  require.resolve("ajv/dist/standalone", { paths: [FRONTEND_DIR] }),
);

const SCHEMA_PATH = path.join(FRONTEND_DIR, "ws-schema.json");
const OUTPUT_PATH = path.join(FRONTEND_DIR, "src", "api", "ws-validator.generated.ts");

const BANNER = `/* @generated from ws-schema.json — do not edit by hand.
 * Regenerate: node scripts/compile-validators.cjs
 * Or: uv run python scripts/export_schemas.py --types
 */

/* eslint-disable */
// @ts-nocheck`;

function main() {
  const schema = JSON.parse(fs.readFileSync(SCHEMA_PATH, "utf8"));

  // Pydantic emits discriminator as { propertyName, mapping } but Ajv only
  // supports { propertyName }. Same stripping as the old ws-validator.ts runtime path.
  schema.discriminator = { propertyName: schema.discriminator.propertyName };

  const ajv = new Ajv({
    discriminator: true,
    strict: false,
    code: { source: true, esm: true },
  });

  const validate = ajv.compile(schema);
  const code = standaloneCode(ajv, validate);

  const output = `${BANNER}\n\n${code}\n`;
  fs.writeFileSync(OUTPUT_PATH, output);
  console.log(`Wrote ${OUTPUT_PATH}`);
}

main();
