import { describe, expect, it } from "vitest";

import { validateWsMessage, WsValidationError } from "./ws-validator";

describe("validateWsMessage", () => {
  it("validates a connected message", () => {
    const msg = {
      type: "connected",
      data: { uptime_seconds: 123.4, entity_count: 50, app_count: 3, version: "0.25.0" },
      timestamp: 1700000000,
    };
    expect(validateWsMessage(msg)).toEqual(msg);
  });

  it("validates an execution_completed message with array data", () => {
    const msg = {
      type: "execution_completed",
      data: [
        {
          kind: "handler",
          listener_id: 1,
          app_key: "my_app",
          instance_index: 0,
          status: "success",
          duration_ms: 42,
          error_type: null,
        },
      ],
      timestamp: 1700000000,
    };
    expect(validateWsMessage(msg)).toEqual(msg);
  });

  it("validates a log message", () => {
    const msg = {
      type: "log",
      data: {
        seq: 1,
        timestamp: 1700000000,
        level: "INFO",
        logger_name: "hassette.test",
        func_name: null,
        lineno: null,
        message: "hello",
        exc_info: null,
        app_key: null,
        execution_id: null,
        instance_name: null,
        instance_index: null,
        source_tier: null,
      },
      timestamp: 1700000000,
    };
    expect(validateWsMessage(msg)).toEqual(msg);
  });

  it("throws WsValidationError for incomplete message (missing timestamp and app_count)", () => {
    const msg = {
      type: "connected",
      data: { uptime_seconds: 123.4, entity_count: 50 },
    };
    expect(() => validateWsMessage(msg)).toThrow(WsValidationError);
  });

  it("throws WsValidationError for unknown type value", () => {
    const msg = {
      type: "unknown_type",
      data: {},
      timestamp: 1700000000,
    };
    expect(() => validateWsMessage(msg)).toThrow(WsValidationError);
  });

  it("throws WsValidationError for non-object input", () => {
    expect(() => validateWsMessage(42)).toThrow(WsValidationError);
    expect(() => validateWsMessage("hello")).toThrow(WsValidationError);
    expect(() => validateWsMessage(null)).toThrow(WsValidationError);
  });

  it("exposes validation errors on the thrown error", () => {
    expect.assertions(3);
    try {
      validateWsMessage({ type: "connected", data: {} });
    } catch (err) {
      expect(err).toBeInstanceOf(WsValidationError);
      expect((err as WsValidationError).errors).toBeDefined();
      expect((err as WsValidationError).errors.length).toBeGreaterThan(0);
    }
  });
});
