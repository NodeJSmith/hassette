import type { ErrorObject, ValidateFunction } from "ajv/dist/types";

import type { WsServerMessage } from "./ws-types";
import { validate as _validate } from "./ws-validator.generated";

const validate = _validate as ValidateFunction<WsServerMessage>;

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
      {
        message: "expected object with type field",
        keyword: "type",
        instancePath: "",
        schemaPath: "#/discriminator",
        params: { type: "object" },
      },
    ]);
  }
  if (validate(data)) {
    return data;
  }
  throw new WsValidationError(validate.errors ?? []);
}
