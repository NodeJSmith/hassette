import type { ErrorObject, ValidateFunction } from "ajv/dist/types";

import type { WsServerMessage } from "./ws-types";
import { validate as validateGenerated } from "./ws-validator.generated";

const ajvValidate = validateGenerated as ValidateFunction<WsServerMessage>;

const EXPECTED_TYPE_KEYWORD = "type";
const EXPECTED_TYPE_VALUE = "object";

export class WsValidationError extends Error {
  errors: ErrorObject[];

  constructor(errors: ErrorObject[]) {
    super("WebSocket message validation failed");
    this.name = "WsValidationError";
    this.errors = errors;
  }
}

function makeMissingTypeFieldError(): ErrorObject {
  return {
    message: "expected object with type field",
    keyword: EXPECTED_TYPE_KEYWORD,
    instancePath: "",
    schemaPath: "#/discriminator",
    params: { type: EXPECTED_TYPE_VALUE },
  };
}

export function validateWsMessage(message: unknown): WsServerMessage {
  if (typeof message !== "object" || message === null || !(EXPECTED_TYPE_KEYWORD in message)) {
    throw new WsValidationError([makeMissingTypeFieldError()]);
  }
  if (ajvValidate(message)) {
    return message;
  }
  throw new WsValidationError(ajvValidate.errors ?? []);
}
