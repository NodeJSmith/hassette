import type { ErrorObject, ValidateFunction } from "ajv/dist/types";

import type { WsServerMessage } from "./ws-types";
import { validate as validateGenerated } from "./ws-validator.generated";

const ajvValidate = validateGenerated as ValidateFunction<WsServerMessage>;

const DISCRIMINATOR_FIELD = "type";

export class WsValidationError extends Error {
  errors: ErrorObject[];

  constructor(errors: ErrorObject[]) {
    super("WebSocket message validation failed");
    this.name = "WsValidationError";
    this.errors = errors;
  }
}

function buildMissingTypeFieldError(): ErrorObject {
  return {
    message: `expected object with ${DISCRIMINATOR_FIELD} field`,
    // ajv's JSON Schema keyword, not the WS field — same string as DISCRIMINATOR_FIELD by coincidence
    keyword: "type",
    instancePath: "",
    schemaPath: "#/discriminator",
    params: { type: "object" },
  };
}

export function validateWsMessage(message: unknown): WsServerMessage {
  if (typeof message !== "object" || message === null || !(DISCRIMINATOR_FIELD in message)) {
    throw new WsValidationError([buildMissingTypeFieldError()]);
  }
  if (ajvValidate(message)) {
    return message;
  }
  throw new WsValidationError(ajvValidate.errors ?? []);
}
