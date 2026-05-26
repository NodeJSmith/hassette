import Ajv, { type ErrorObject } from "ajv";

import rawSchema from "../../ws-schema.json";
import type { WsServerMessage } from "./ws-types";

// Pydantic emits discriminator as { propertyName, mapping } but AJV only
// supports { propertyName }. Stripping mapping is safe — AJV infers the
// discriminator from the oneOf branch schemas' const type fields instead.
const wsSchema = { ...rawSchema, discriminator: { propertyName: rawSchema.discriminator.propertyName } };

const ajv = new Ajv({ discriminator: true });
const validate = ajv.compile<WsServerMessage>(wsSchema);

export class WsValidationError extends Error {
  errors: ErrorObject[];

  constructor(errors: ErrorObject[]) {
    super("WebSocket message validation failed");
    this.name = "WsValidationError";
    this.errors = errors;
  }
}

export function validateWsMessage(data: unknown): WsServerMessage {
  if (typeof data !== "object" || data === null || !("type" in data)) {
    throw new WsValidationError([
      { message: "expected object with type field", keyword: "", instancePath: "", schemaPath: "", params: {} },
    ]);
  }
  if (validate(data)) {
    return data;
  }
  throw new WsValidationError(validate.errors ?? []);
}
