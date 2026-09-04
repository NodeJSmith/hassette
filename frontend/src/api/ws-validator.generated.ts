/* @generated from ws-schema.json — do not edit by hand.
 * Regenerate: node scripts/compile-validators.cjs
 * Or: uv run python scripts/export_schemas.py --types
 */

/* eslint-disable */
// @ts-nocheck

"use strict";
export const validate = validate10;
export default validate10;
const schema11 = {
  $defs: {
    AppManifestsChangedData: {
      description:
        'Payload for a completed app load/reload pass broadcast over WebSocket.\n\nCarries no fields — it is a refetch signal, not a diff. The event that triggers it\n(``HASSETTE_EVENT_APP_LOAD_COMPLETED``) fires after a full bootstrap or reload pass over\nall apps and does not identify which app(s) changed, so clients should treat receipt as\n"manifest status may be stale, refetch" rather than inspect the payload for detail.',
      properties: {},
      title: "AppManifestsChangedData",
      type: "object",
    },
    AppManifestsChangedWsMessage: {
      properties: {
        type: { const: "app_manifests_changed", title: "Type", type: "string" },
        data: { $ref: "#/$defs/AppManifestsChangedData" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "AppManifestsChangedWsMessage",
      type: "object",
    },
    AppStatusChangedData: {
      description:
        "Payload for an app lifecycle state-change event broadcast over WebSocket.\n\nMirrors ``events.hassette.AppStateChangePayload`` exactly.",
      properties: {
        app_key: { title: "App Key", type: "string" },
        index: { title: "Index", type: "integer" },
        status: { $ref: "#/$defs/ResourceStatus" },
        previous_status: { anyOf: [{ $ref: "#/$defs/ResourceStatus" }, { type: "null" }], default: null },
        instance_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Instance Name" },
        class_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Class Name" },
        exception: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception" },
        exception_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Type" },
        exception_traceback: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          title: "Exception Traceback",
        },
      },
      required: ["app_key", "index", "status"],
      title: "AppStatusChangedData",
      type: "object",
    },
    AppStatusChangedWsMessage: {
      properties: {
        type: { const: "app_status_changed", title: "Type", type: "string" },
        data: { $ref: "#/$defs/AppStatusChangedData" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "AppStatusChangedWsMessage",
      type: "object",
    },
    ConnectedPayload: {
      properties: {
        uptime_seconds: { title: "Uptime Seconds", type: "number" },
        entity_count: { title: "Entity Count", type: "integer" },
        app_count: { title: "App Count", type: "integer" },
        version: { default: "", title: "Version", type: "string" },
      },
      required: ["uptime_seconds", "entity_count", "app_count"],
      title: "ConnectedPayload",
      type: "object",
    },
    ConnectedWsMessage: {
      properties: {
        type: { const: "connected", title: "Type", type: "string" },
        data: { $ref: "#/$defs/ConnectedPayload" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "ConnectedWsMessage",
      type: "object",
    },
    ConnectivityData: {
      description: "Payload for a Home Assistant WebSocket connectivity event.",
      properties: { connected: { title: "Connected", type: "boolean" } },
      required: ["connected"],
      title: "ConnectivityData",
      type: "object",
    },
    ConnectivityWsMessage: {
      properties: {
        type: { const: "connectivity", title: "Type", type: "string" },
        data: { $ref: "#/$defs/ConnectivityData" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "ConnectivityWsMessage",
      type: "object",
    },
    ExecutionCompletedData: {
      description:
        "Payload for execution_completed WebSocket messages.\n\n``kind`` discriminates handler invocations from job executions.\n``listener_id`` is set when ``kind='handler'``; ``job_id`` when ``kind='job'``.",
      properties: {
        kind: { enum: ["handler", "job"], title: "Kind", type: "string" },
        app_key: { title: "App Key", type: "string" },
        instance_index: { title: "Instance Index", type: "integer" },
        status: { $ref: "#/$defs/ExecutionStatus" },
        duration_ms: { title: "Duration Ms", type: "number" },
        error_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Error Type" },
        listener_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Listener Id" },
        job_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Job Id" },
        thread_leaked: { default: false, title: "Thread Leaked", type: "boolean" },
      },
      required: ["kind", "app_key", "instance_index", "status", "duration_ms"],
      title: "ExecutionCompletedData",
      type: "object",
    },
    ExecutionCompletedWsMessage: {
      properties: {
        type: { const: "execution_completed", title: "Type", type: "string" },
        data: { items: { $ref: "#/$defs/ExecutionCompletedData" }, title: "Data", type: "array" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "ExecutionCompletedWsMessage",
      type: "object",
    },
    ExecutionStatus: {
      description:
        "Status values for handler invocations and job executions.\n\nCovers all values allowed by the ``executions.status`` CHECK constraint: migration 001\nintroduced the original four values (``success``, ``error``, ``cancelled``, ``timed_out``);\nmigration 009 added ``skipped``.\nPydantic v2 coerces plain strings to enum members on construction and\nserialises back to plain strings in JSON responses.",
      enum: ["success", "error", "cancelled", "timed_out", "skipped"],
      title: "ExecutionStatus",
      type: "string",
    },
    LogEntryResponse: {
      properties: {
        seq: { title: "Seq", type: "integer" },
        timestamp: { title: "Timestamp", type: "number" },
        level: { enum: ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], title: "Level", type: "string" },
        logger_name: { title: "Logger Name", type: "string" },
        func_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Func Name" },
        lineno: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Lineno" },
        message: { title: "Message", type: "string" },
        exc_info: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exc Info" },
        app_key: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "App Key" },
        execution_id: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Execution Id" },
        instance_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Instance Name" },
        instance_index: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Instance Index" },
        source_tier: {
          anyOf: [{ enum: ["app", "framework"], type: "string" }, { type: "null" }],
          default: null,
          title: "Source Tier",
        },
        execution_kind: {
          anyOf: [{ enum: ["handler", "job"], type: "string" }, { type: "null" }],
          default: null,
          title: "Execution Kind",
        },
        listener_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Listener Id" },
        job_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Job Id" },
      },
      required: ["seq", "timestamp", "level", "logger_name", "message"],
      title: "LogEntryResponse",
      type: "object",
    },
    LogWsMessage: {
      properties: {
        type: { const: "log", title: "Type", type: "string" },
        data: { $ref: "#/$defs/LogEntryResponse" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "LogWsMessage",
      type: "object",
    },
    ResourceStatus: {
      description: "Enumeration for resource status.",
      enum: [
        "not_started",
        "starting",
        "running",
        "stopping",
        "stopped",
        "failed",
        "crashed",
        "exhausted_dead",
        "exhausted_cooling",
      ],
      title: "ResourceStatus",
      type: "string",
    },
    ServiceStatusData: {
      description:
        "Payload for an internal service status-change event broadcast over WebSocket.\n\nMirrors ``events.hassette.ServiceStatusPayload``.",
      properties: {
        resource_name: { title: "Resource Name", type: "string" },
        role: { title: "Role", type: "string" },
        status: { $ref: "#/$defs/ResourceStatus" },
        previous_status: { anyOf: [{ $ref: "#/$defs/ResourceStatus" }, { type: "null" }], default: null },
        exception: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception" },
        exception_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Type" },
        exception_traceback: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          title: "Exception Traceback",
        },
        retry_at: { anyOf: [{ type: "number" }, { type: "null" }], default: null, title: "Retry At" },
        ready: { default: false, title: "Ready", type: "boolean" },
        ready_phase: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Ready Phase" },
      },
      required: ["resource_name", "role", "status"],
      title: "ServiceStatusData",
      type: "object",
    },
    ServiceStatusWsMessage: {
      properties: {
        type: { const: "service_status", title: "Type", type: "string" },
        data: { $ref: "#/$defs/ServiceStatusData" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "ServiceStatusWsMessage",
      type: "object",
    },
  },
  discriminator: { propertyName: "type" },
  oneOf: [
    { $ref: "#/$defs/AppStatusChangedWsMessage" },
    { $ref: "#/$defs/LogWsMessage" },
    { $ref: "#/$defs/ConnectedWsMessage" },
    { $ref: "#/$defs/ConnectivityWsMessage" },
    { $ref: "#/$defs/ServiceStatusWsMessage" },
    { $ref: "#/$defs/ExecutionCompletedWsMessage" },
    { $ref: "#/$defs/AppManifestsChangedWsMessage" },
  ],
};
const schema12 = {
  properties: {
    type: { const: "app_status_changed", title: "Type", type: "string" },
    data: { $ref: "#/$defs/AppStatusChangedData" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "AppStatusChangedWsMessage",
  type: "object",
};
const schema13 = {
  description:
    "Payload for an app lifecycle state-change event broadcast over WebSocket.\n\nMirrors ``events.hassette.AppStateChangePayload`` exactly.",
  properties: {
    app_key: { title: "App Key", type: "string" },
    index: { title: "Index", type: "integer" },
    status: { $ref: "#/$defs/ResourceStatus" },
    previous_status: { anyOf: [{ $ref: "#/$defs/ResourceStatus" }, { type: "null" }], default: null },
    instance_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Instance Name" },
    class_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Class Name" },
    exception: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception" },
    exception_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Type" },
    exception_traceback: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Traceback" },
  },
  required: ["app_key", "index", "status"],
  title: "AppStatusChangedData",
  type: "object",
};
const schema14 = {
  description: "Enumeration for resource status.",
  enum: [
    "not_started",
    "starting",
    "running",
    "stopping",
    "stopped",
    "failed",
    "crashed",
    "exhausted_dead",
    "exhausted_cooling",
  ],
  title: "ResourceStatus",
  type: "string",
};
function validate12(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.app_key === undefined && (missing0 = "app_key")) ||
        (data.index === undefined && (missing0 = "index")) ||
        (data.status === undefined && (missing0 = "status"))
      ) {
        validate12.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.app_key !== undefined) {
          const _errs1 = errors;
          if (typeof data.app_key !== "string") {
            validate12.errors = [
              {
                instancePath: instancePath + "/app_key",
                schemaPath: "#/properties/app_key/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.index !== undefined) {
            let data1 = data.index;
            const _errs3 = errors;
            if (!(typeof data1 == "number" && !(data1 % 1) && !isNaN(data1))) {
              validate12.errors = [
                {
                  instancePath: instancePath + "/index",
                  schemaPath: "#/properties/index/type",
                  keyword: "type",
                  params: { type: "integer" },
                  message: "must be integer",
                },
              ];
              return false;
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.status !== undefined) {
              let data2 = data.status;
              const _errs5 = errors;
              if (typeof data2 !== "string") {
                validate12.errors = [
                  {
                    instancePath: instancePath + "/status",
                    schemaPath: "#/$defs/ResourceStatus/type",
                    keyword: "type",
                    params: { type: "string" },
                    message: "must be string",
                  },
                ];
                return false;
              }
              if (!(
                data2 === "not_started" ||
                data2 === "starting" ||
                data2 === "running" ||
                data2 === "stopping" ||
                data2 === "stopped" ||
                data2 === "failed" ||
                data2 === "crashed" ||
                data2 === "exhausted_dead" ||
                data2 === "exhausted_cooling"
              )) {
                validate12.errors = [
                  {
                    instancePath: instancePath + "/status",
                    schemaPath: "#/$defs/ResourceStatus/enum",
                    keyword: "enum",
                    params: { allowedValues: schema14.enum },
                    message: "must be equal to one of the allowed values",
                  },
                ];
                return false;
              }
              var valid0 = _errs5 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.previous_status !== undefined) {
                let data3 = data.previous_status;
                const _errs8 = errors;
                const _errs9 = errors;
                let valid2 = false;
                const _errs10 = errors;
                if (typeof data3 !== "string") {
                  const err0 = {
                    instancePath: instancePath + "/previous_status",
                    schemaPath: "#/$defs/ResourceStatus/type",
                    keyword: "type",
                    params: { type: "string" },
                    message: "must be string",
                  };
                  if (vErrors === null) {
                    vErrors = [err0];
                  } else {
                    vErrors.push(err0);
                  }
                  errors++;
                }
                if (!(
                  data3 === "not_started" ||
                  data3 === "starting" ||
                  data3 === "running" ||
                  data3 === "stopping" ||
                  data3 === "stopped" ||
                  data3 === "failed" ||
                  data3 === "crashed" ||
                  data3 === "exhausted_dead" ||
                  data3 === "exhausted_cooling"
                )) {
                  const err1 = {
                    instancePath: instancePath + "/previous_status",
                    schemaPath: "#/$defs/ResourceStatus/enum",
                    keyword: "enum",
                    params: { allowedValues: schema14.enum },
                    message: "must be equal to one of the allowed values",
                  };
                  if (vErrors === null) {
                    vErrors = [err1];
                  } else {
                    vErrors.push(err1);
                  }
                  errors++;
                }
                var _valid0 = _errs10 === errors;
                valid2 = valid2 || _valid0;
                if (!valid2) {
                  const _errs13 = errors;
                  if (data3 !== null) {
                    const err2 = {
                      instancePath: instancePath + "/previous_status",
                      schemaPath: "#/properties/previous_status/anyOf/1/type",
                      keyword: "type",
                      params: { type: "null" },
                      message: "must be null",
                    };
                    if (vErrors === null) {
                      vErrors = [err2];
                    } else {
                      vErrors.push(err2);
                    }
                    errors++;
                  }
                  var _valid0 = _errs13 === errors;
                  valid2 = valid2 || _valid0;
                }
                if (!valid2) {
                  const err3 = {
                    instancePath: instancePath + "/previous_status",
                    schemaPath: "#/properties/previous_status/anyOf",
                    keyword: "anyOf",
                    params: {},
                    message: "must match a schema in anyOf",
                  };
                  if (vErrors === null) {
                    vErrors = [err3];
                  } else {
                    vErrors.push(err3);
                  }
                  errors++;
                  validate12.errors = vErrors;
                  return false;
                } else {
                  errors = _errs9;
                  if (vErrors !== null) {
                    if (_errs9) {
                      vErrors.length = _errs9;
                    } else {
                      vErrors = null;
                    }
                  }
                }
                var valid0 = _errs8 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.instance_name !== undefined) {
                  let data4 = data.instance_name;
                  const _errs15 = errors;
                  const _errs16 = errors;
                  let valid4 = false;
                  const _errs17 = errors;
                  if (typeof data4 !== "string") {
                    const err4 = {
                      instancePath: instancePath + "/instance_name",
                      schemaPath: "#/properties/instance_name/anyOf/0/type",
                      keyword: "type",
                      params: { type: "string" },
                      message: "must be string",
                    };
                    if (vErrors === null) {
                      vErrors = [err4];
                    } else {
                      vErrors.push(err4);
                    }
                    errors++;
                  }
                  var _valid1 = _errs17 === errors;
                  valid4 = valid4 || _valid1;
                  if (!valid4) {
                    const _errs19 = errors;
                    if (data4 !== null) {
                      const err5 = {
                        instancePath: instancePath + "/instance_name",
                        schemaPath: "#/properties/instance_name/anyOf/1/type",
                        keyword: "type",
                        params: { type: "null" },
                        message: "must be null",
                      };
                      if (vErrors === null) {
                        vErrors = [err5];
                      } else {
                        vErrors.push(err5);
                      }
                      errors++;
                    }
                    var _valid1 = _errs19 === errors;
                    valid4 = valid4 || _valid1;
                  }
                  if (!valid4) {
                    const err6 = {
                      instancePath: instancePath + "/instance_name",
                      schemaPath: "#/properties/instance_name/anyOf",
                      keyword: "anyOf",
                      params: {},
                      message: "must match a schema in anyOf",
                    };
                    if (vErrors === null) {
                      vErrors = [err6];
                    } else {
                      vErrors.push(err6);
                    }
                    errors++;
                    validate12.errors = vErrors;
                    return false;
                  } else {
                    errors = _errs16;
                    if (vErrors !== null) {
                      if (_errs16) {
                        vErrors.length = _errs16;
                      } else {
                        vErrors = null;
                      }
                    }
                  }
                  var valid0 = _errs15 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.class_name !== undefined) {
                    let data5 = data.class_name;
                    const _errs21 = errors;
                    const _errs22 = errors;
                    let valid5 = false;
                    const _errs23 = errors;
                    if (typeof data5 !== "string") {
                      const err7 = {
                        instancePath: instancePath + "/class_name",
                        schemaPath: "#/properties/class_name/anyOf/0/type",
                        keyword: "type",
                        params: { type: "string" },
                        message: "must be string",
                      };
                      if (vErrors === null) {
                        vErrors = [err7];
                      } else {
                        vErrors.push(err7);
                      }
                      errors++;
                    }
                    var _valid2 = _errs23 === errors;
                    valid5 = valid5 || _valid2;
                    if (!valid5) {
                      const _errs25 = errors;
                      if (data5 !== null) {
                        const err8 = {
                          instancePath: instancePath + "/class_name",
                          schemaPath: "#/properties/class_name/anyOf/1/type",
                          keyword: "type",
                          params: { type: "null" },
                          message: "must be null",
                        };
                        if (vErrors === null) {
                          vErrors = [err8];
                        } else {
                          vErrors.push(err8);
                        }
                        errors++;
                      }
                      var _valid2 = _errs25 === errors;
                      valid5 = valid5 || _valid2;
                    }
                    if (!valid5) {
                      const err9 = {
                        instancePath: instancePath + "/class_name",
                        schemaPath: "#/properties/class_name/anyOf",
                        keyword: "anyOf",
                        params: {},
                        message: "must match a schema in anyOf",
                      };
                      if (vErrors === null) {
                        vErrors = [err9];
                      } else {
                        vErrors.push(err9);
                      }
                      errors++;
                      validate12.errors = vErrors;
                      return false;
                    } else {
                      errors = _errs22;
                      if (vErrors !== null) {
                        if (_errs22) {
                          vErrors.length = _errs22;
                        } else {
                          vErrors = null;
                        }
                      }
                    }
                    var valid0 = _errs21 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.exception !== undefined) {
                      let data6 = data.exception;
                      const _errs27 = errors;
                      const _errs28 = errors;
                      let valid6 = false;
                      const _errs29 = errors;
                      if (typeof data6 !== "string") {
                        const err10 = {
                          instancePath: instancePath + "/exception",
                          schemaPath: "#/properties/exception/anyOf/0/type",
                          keyword: "type",
                          params: { type: "string" },
                          message: "must be string",
                        };
                        if (vErrors === null) {
                          vErrors = [err10];
                        } else {
                          vErrors.push(err10);
                        }
                        errors++;
                      }
                      var _valid3 = _errs29 === errors;
                      valid6 = valid6 || _valid3;
                      if (!valid6) {
                        const _errs31 = errors;
                        if (data6 !== null) {
                          const err11 = {
                            instancePath: instancePath + "/exception",
                            schemaPath: "#/properties/exception/anyOf/1/type",
                            keyword: "type",
                            params: { type: "null" },
                            message: "must be null",
                          };
                          if (vErrors === null) {
                            vErrors = [err11];
                          } else {
                            vErrors.push(err11);
                          }
                          errors++;
                        }
                        var _valid3 = _errs31 === errors;
                        valid6 = valid6 || _valid3;
                      }
                      if (!valid6) {
                        const err12 = {
                          instancePath: instancePath + "/exception",
                          schemaPath: "#/properties/exception/anyOf",
                          keyword: "anyOf",
                          params: {},
                          message: "must match a schema in anyOf",
                        };
                        if (vErrors === null) {
                          vErrors = [err12];
                        } else {
                          vErrors.push(err12);
                        }
                        errors++;
                        validate12.errors = vErrors;
                        return false;
                      } else {
                        errors = _errs28;
                        if (vErrors !== null) {
                          if (_errs28) {
                            vErrors.length = _errs28;
                          } else {
                            vErrors = null;
                          }
                        }
                      }
                      var valid0 = _errs27 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.exception_type !== undefined) {
                        let data7 = data.exception_type;
                        const _errs33 = errors;
                        const _errs34 = errors;
                        let valid7 = false;
                        const _errs35 = errors;
                        if (typeof data7 !== "string") {
                          const err13 = {
                            instancePath: instancePath + "/exception_type",
                            schemaPath: "#/properties/exception_type/anyOf/0/type",
                            keyword: "type",
                            params: { type: "string" },
                            message: "must be string",
                          };
                          if (vErrors === null) {
                            vErrors = [err13];
                          } else {
                            vErrors.push(err13);
                          }
                          errors++;
                        }
                        var _valid4 = _errs35 === errors;
                        valid7 = valid7 || _valid4;
                        if (!valid7) {
                          const _errs37 = errors;
                          if (data7 !== null) {
                            const err14 = {
                              instancePath: instancePath + "/exception_type",
                              schemaPath: "#/properties/exception_type/anyOf/1/type",
                              keyword: "type",
                              params: { type: "null" },
                              message: "must be null",
                            };
                            if (vErrors === null) {
                              vErrors = [err14];
                            } else {
                              vErrors.push(err14);
                            }
                            errors++;
                          }
                          var _valid4 = _errs37 === errors;
                          valid7 = valid7 || _valid4;
                        }
                        if (!valid7) {
                          const err15 = {
                            instancePath: instancePath + "/exception_type",
                            schemaPath: "#/properties/exception_type/anyOf",
                            keyword: "anyOf",
                            params: {},
                            message: "must match a schema in anyOf",
                          };
                          if (vErrors === null) {
                            vErrors = [err15];
                          } else {
                            vErrors.push(err15);
                          }
                          errors++;
                          validate12.errors = vErrors;
                          return false;
                        } else {
                          errors = _errs34;
                          if (vErrors !== null) {
                            if (_errs34) {
                              vErrors.length = _errs34;
                            } else {
                              vErrors = null;
                            }
                          }
                        }
                        var valid0 = _errs33 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.exception_traceback !== undefined) {
                          let data8 = data.exception_traceback;
                          const _errs39 = errors;
                          const _errs40 = errors;
                          let valid8 = false;
                          const _errs41 = errors;
                          if (typeof data8 !== "string") {
                            const err16 = {
                              instancePath: instancePath + "/exception_traceback",
                              schemaPath: "#/properties/exception_traceback/anyOf/0/type",
                              keyword: "type",
                              params: { type: "string" },
                              message: "must be string",
                            };
                            if (vErrors === null) {
                              vErrors = [err16];
                            } else {
                              vErrors.push(err16);
                            }
                            errors++;
                          }
                          var _valid5 = _errs41 === errors;
                          valid8 = valid8 || _valid5;
                          if (!valid8) {
                            const _errs43 = errors;
                            if (data8 !== null) {
                              const err17 = {
                                instancePath: instancePath + "/exception_traceback",
                                schemaPath: "#/properties/exception_traceback/anyOf/1/type",
                                keyword: "type",
                                params: { type: "null" },
                                message: "must be null",
                              };
                              if (vErrors === null) {
                                vErrors = [err17];
                              } else {
                                vErrors.push(err17);
                              }
                              errors++;
                            }
                            var _valid5 = _errs43 === errors;
                            valid8 = valid8 || _valid5;
                          }
                          if (!valid8) {
                            const err18 = {
                              instancePath: instancePath + "/exception_traceback",
                              schemaPath: "#/properties/exception_traceback/anyOf",
                              keyword: "anyOf",
                              params: {},
                              message: "must match a schema in anyOf",
                            };
                            if (vErrors === null) {
                              vErrors = [err18];
                            } else {
                              vErrors.push(err18);
                            }
                            errors++;
                            validate12.errors = vErrors;
                            return false;
                          } else {
                            errors = _errs40;
                            if (vErrors !== null) {
                              if (_errs40) {
                                vErrors.length = _errs40;
                              } else {
                                vErrors = null;
                              }
                            }
                          }
                          var valid0 = _errs39 === errors;
                        } else {
                          var valid0 = true;
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    } else {
      validate12.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate12.errors = vErrors;
  return errors === 0;
}
function validate11(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.type === undefined && (missing0 = "type")) ||
        (data.data === undefined && (missing0 = "data")) ||
        (data.timestamp === undefined && (missing0 = "timestamp"))
      ) {
        validate11.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.type !== undefined) {
          let data0 = data.type;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate11.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          if ("app_status_changed" !== data0) {
            validate11.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "app_status_changed" },
                message: "must be equal to constant",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.data !== undefined) {
            const _errs3 = errors;
            if (
              !validate12(data.data, {
                instancePath: instancePath + "/data",
                parentData: data,
                parentDataProperty: "data",
                rootData,
              })
            ) {
              vErrors = vErrors === null ? validate12.errors : vErrors.concat(validate12.errors);
              errors = vErrors.length;
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.timestamp !== undefined) {
              const _errs4 = errors;
              if (!(typeof data.timestamp == "number")) {
                validate11.errors = [
                  {
                    instancePath: instancePath + "/timestamp",
                    schemaPath: "#/properties/timestamp/type",
                    keyword: "type",
                    params: { type: "number" },
                    message: "must be number",
                  },
                ];
                return false;
              }
              var valid0 = _errs4 === errors;
            } else {
              var valid0 = true;
            }
          }
        }
      }
    } else {
      validate11.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate11.errors = vErrors;
  return errors === 0;
}
const schema16 = {
  properties: {
    type: { const: "log", title: "Type", type: "string" },
    data: { $ref: "#/$defs/LogEntryResponse" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "LogWsMessage",
  type: "object",
};
const schema17 = {
  properties: {
    seq: { title: "Seq", type: "integer" },
    timestamp: { title: "Timestamp", type: "number" },
    level: { enum: ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], title: "Level", type: "string" },
    logger_name: { title: "Logger Name", type: "string" },
    func_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Func Name" },
    lineno: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Lineno" },
    message: { title: "Message", type: "string" },
    exc_info: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exc Info" },
    app_key: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "App Key" },
    execution_id: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Execution Id" },
    instance_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Instance Name" },
    instance_index: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Instance Index" },
    source_tier: {
      anyOf: [{ enum: ["app", "framework"], type: "string" }, { type: "null" }],
      default: null,
      title: "Source Tier",
    },
    execution_kind: {
      anyOf: [{ enum: ["handler", "job"], type: "string" }, { type: "null" }],
      default: null,
      title: "Execution Kind",
    },
    listener_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Listener Id" },
    job_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Job Id" },
  },
  required: ["seq", "timestamp", "level", "logger_name", "message"],
  title: "LogEntryResponse",
  type: "object",
};
function validate14(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.type === undefined && (missing0 = "type")) ||
        (data.data === undefined && (missing0 = "data")) ||
        (data.timestamp === undefined && (missing0 = "timestamp"))
      ) {
        validate14.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.type !== undefined) {
          let data0 = data.type;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate14.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          if ("log" !== data0) {
            validate14.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "log" },
                message: "must be equal to constant",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.data !== undefined) {
            let data1 = data.data;
            const _errs3 = errors;
            const _errs4 = errors;
            if (errors === _errs4) {
              if (data1 && typeof data1 == "object" && !Array.isArray(data1)) {
                let missing1;
                if (
                  (data1.seq === undefined && (missing1 = "seq")) ||
                  (data1.timestamp === undefined && (missing1 = "timestamp")) ||
                  (data1.level === undefined && (missing1 = "level")) ||
                  (data1.logger_name === undefined && (missing1 = "logger_name")) ||
                  (data1.message === undefined && (missing1 = "message"))
                ) {
                  validate14.errors = [
                    {
                      instancePath: instancePath + "/data",
                      schemaPath: "#/$defs/LogEntryResponse/required",
                      keyword: "required",
                      params: { missingProperty: missing1 },
                      message: "must have required property '" + missing1 + "'",
                    },
                  ];
                  return false;
                } else {
                  if (data1.seq !== undefined) {
                    let data2 = data1.seq;
                    const _errs6 = errors;
                    if (!(typeof data2 == "number" && !(data2 % 1) && !isNaN(data2))) {
                      validate14.errors = [
                        {
                          instancePath: instancePath + "/data/seq",
                          schemaPath: "#/$defs/LogEntryResponse/properties/seq/type",
                          keyword: "type",
                          params: { type: "integer" },
                          message: "must be integer",
                        },
                      ];
                      return false;
                    }
                    var valid2 = _errs6 === errors;
                  } else {
                    var valid2 = true;
                  }
                  if (valid2) {
                    if (data1.timestamp !== undefined) {
                      const _errs8 = errors;
                      if (!(typeof data1.timestamp == "number")) {
                        validate14.errors = [
                          {
                            instancePath: instancePath + "/data/timestamp",
                            schemaPath: "#/$defs/LogEntryResponse/properties/timestamp/type",
                            keyword: "type",
                            params: { type: "number" },
                            message: "must be number",
                          },
                        ];
                        return false;
                      }
                      var valid2 = _errs8 === errors;
                    } else {
                      var valid2 = true;
                    }
                    if (valid2) {
                      if (data1.level !== undefined) {
                        let data4 = data1.level;
                        const _errs10 = errors;
                        if (typeof data4 !== "string") {
                          validate14.errors = [
                            {
                              instancePath: instancePath + "/data/level",
                              schemaPath: "#/$defs/LogEntryResponse/properties/level/type",
                              keyword: "type",
                              params: { type: "string" },
                              message: "must be string",
                            },
                          ];
                          return false;
                        }
                        if (!(
                          data4 === "DEBUG" ||
                          data4 === "INFO" ||
                          data4 === "WARNING" ||
                          data4 === "ERROR" ||
                          data4 === "CRITICAL"
                        )) {
                          validate14.errors = [
                            {
                              instancePath: instancePath + "/data/level",
                              schemaPath: "#/$defs/LogEntryResponse/properties/level/enum",
                              keyword: "enum",
                              params: { allowedValues: schema17.properties.level.enum },
                              message: "must be equal to one of the allowed values",
                            },
                          ];
                          return false;
                        }
                        var valid2 = _errs10 === errors;
                      } else {
                        var valid2 = true;
                      }
                      if (valid2) {
                        if (data1.logger_name !== undefined) {
                          const _errs12 = errors;
                          if (typeof data1.logger_name !== "string") {
                            validate14.errors = [
                              {
                                instancePath: instancePath + "/data/logger_name",
                                schemaPath: "#/$defs/LogEntryResponse/properties/logger_name/type",
                                keyword: "type",
                                params: { type: "string" },
                                message: "must be string",
                              },
                            ];
                            return false;
                          }
                          var valid2 = _errs12 === errors;
                        } else {
                          var valid2 = true;
                        }
                        if (valid2) {
                          if (data1.func_name !== undefined) {
                            let data6 = data1.func_name;
                            const _errs14 = errors;
                            const _errs15 = errors;
                            let valid3 = false;
                            const _errs16 = errors;
                            if (typeof data6 !== "string") {
                              const err0 = {
                                instancePath: instancePath + "/data/func_name",
                                schemaPath: "#/$defs/LogEntryResponse/properties/func_name/anyOf/0/type",
                                keyword: "type",
                                params: { type: "string" },
                                message: "must be string",
                              };
                              if (vErrors === null) {
                                vErrors = [err0];
                              } else {
                                vErrors.push(err0);
                              }
                              errors++;
                            }
                            var _valid0 = _errs16 === errors;
                            valid3 = valid3 || _valid0;
                            if (!valid3) {
                              const _errs18 = errors;
                              if (data6 !== null) {
                                const err1 = {
                                  instancePath: instancePath + "/data/func_name",
                                  schemaPath: "#/$defs/LogEntryResponse/properties/func_name/anyOf/1/type",
                                  keyword: "type",
                                  params: { type: "null" },
                                  message: "must be null",
                                };
                                if (vErrors === null) {
                                  vErrors = [err1];
                                } else {
                                  vErrors.push(err1);
                                }
                                errors++;
                              }
                              var _valid0 = _errs18 === errors;
                              valid3 = valid3 || _valid0;
                            }
                            if (!valid3) {
                              const err2 = {
                                instancePath: instancePath + "/data/func_name",
                                schemaPath: "#/$defs/LogEntryResponse/properties/func_name/anyOf",
                                keyword: "anyOf",
                                params: {},
                                message: "must match a schema in anyOf",
                              };
                              if (vErrors === null) {
                                vErrors = [err2];
                              } else {
                                vErrors.push(err2);
                              }
                              errors++;
                              validate14.errors = vErrors;
                              return false;
                            } else {
                              errors = _errs15;
                              if (vErrors !== null) {
                                if (_errs15) {
                                  vErrors.length = _errs15;
                                } else {
                                  vErrors = null;
                                }
                              }
                            }
                            var valid2 = _errs14 === errors;
                          } else {
                            var valid2 = true;
                          }
                          if (valid2) {
                            if (data1.lineno !== undefined) {
                              let data7 = data1.lineno;
                              const _errs20 = errors;
                              const _errs21 = errors;
                              let valid4 = false;
                              const _errs22 = errors;
                              if (!(typeof data7 == "number" && !(data7 % 1) && !isNaN(data7))) {
                                const err3 = {
                                  instancePath: instancePath + "/data/lineno",
                                  schemaPath: "#/$defs/LogEntryResponse/properties/lineno/anyOf/0/type",
                                  keyword: "type",
                                  params: { type: "integer" },
                                  message: "must be integer",
                                };
                                if (vErrors === null) {
                                  vErrors = [err3];
                                } else {
                                  vErrors.push(err3);
                                }
                                errors++;
                              }
                              var _valid1 = _errs22 === errors;
                              valid4 = valid4 || _valid1;
                              if (!valid4) {
                                const _errs24 = errors;
                                if (data7 !== null) {
                                  const err4 = {
                                    instancePath: instancePath + "/data/lineno",
                                    schemaPath: "#/$defs/LogEntryResponse/properties/lineno/anyOf/1/type",
                                    keyword: "type",
                                    params: { type: "null" },
                                    message: "must be null",
                                  };
                                  if (vErrors === null) {
                                    vErrors = [err4];
                                  } else {
                                    vErrors.push(err4);
                                  }
                                  errors++;
                                }
                                var _valid1 = _errs24 === errors;
                                valid4 = valid4 || _valid1;
                              }
                              if (!valid4) {
                                const err5 = {
                                  instancePath: instancePath + "/data/lineno",
                                  schemaPath: "#/$defs/LogEntryResponse/properties/lineno/anyOf",
                                  keyword: "anyOf",
                                  params: {},
                                  message: "must match a schema in anyOf",
                                };
                                if (vErrors === null) {
                                  vErrors = [err5];
                                } else {
                                  vErrors.push(err5);
                                }
                                errors++;
                                validate14.errors = vErrors;
                                return false;
                              } else {
                                errors = _errs21;
                                if (vErrors !== null) {
                                  if (_errs21) {
                                    vErrors.length = _errs21;
                                  } else {
                                    vErrors = null;
                                  }
                                }
                              }
                              var valid2 = _errs20 === errors;
                            } else {
                              var valid2 = true;
                            }
                            if (valid2) {
                              if (data1.message !== undefined) {
                                const _errs26 = errors;
                                if (typeof data1.message !== "string") {
                                  validate14.errors = [
                                    {
                                      instancePath: instancePath + "/data/message",
                                      schemaPath: "#/$defs/LogEntryResponse/properties/message/type",
                                      keyword: "type",
                                      params: { type: "string" },
                                      message: "must be string",
                                    },
                                  ];
                                  return false;
                                }
                                var valid2 = _errs26 === errors;
                              } else {
                                var valid2 = true;
                              }
                              if (valid2) {
                                if (data1.exc_info !== undefined) {
                                  let data9 = data1.exc_info;
                                  const _errs28 = errors;
                                  const _errs29 = errors;
                                  let valid5 = false;
                                  const _errs30 = errors;
                                  if (typeof data9 !== "string") {
                                    const err6 = {
                                      instancePath: instancePath + "/data/exc_info",
                                      schemaPath: "#/$defs/LogEntryResponse/properties/exc_info/anyOf/0/type",
                                      keyword: "type",
                                      params: { type: "string" },
                                      message: "must be string",
                                    };
                                    if (vErrors === null) {
                                      vErrors = [err6];
                                    } else {
                                      vErrors.push(err6);
                                    }
                                    errors++;
                                  }
                                  var _valid2 = _errs30 === errors;
                                  valid5 = valid5 || _valid2;
                                  if (!valid5) {
                                    const _errs32 = errors;
                                    if (data9 !== null) {
                                      const err7 = {
                                        instancePath: instancePath + "/data/exc_info",
                                        schemaPath: "#/$defs/LogEntryResponse/properties/exc_info/anyOf/1/type",
                                        keyword: "type",
                                        params: { type: "null" },
                                        message: "must be null",
                                      };
                                      if (vErrors === null) {
                                        vErrors = [err7];
                                      } else {
                                        vErrors.push(err7);
                                      }
                                      errors++;
                                    }
                                    var _valid2 = _errs32 === errors;
                                    valid5 = valid5 || _valid2;
                                  }
                                  if (!valid5) {
                                    const err8 = {
                                      instancePath: instancePath + "/data/exc_info",
                                      schemaPath: "#/$defs/LogEntryResponse/properties/exc_info/anyOf",
                                      keyword: "anyOf",
                                      params: {},
                                      message: "must match a schema in anyOf",
                                    };
                                    if (vErrors === null) {
                                      vErrors = [err8];
                                    } else {
                                      vErrors.push(err8);
                                    }
                                    errors++;
                                    validate14.errors = vErrors;
                                    return false;
                                  } else {
                                    errors = _errs29;
                                    if (vErrors !== null) {
                                      if (_errs29) {
                                        vErrors.length = _errs29;
                                      } else {
                                        vErrors = null;
                                      }
                                    }
                                  }
                                  var valid2 = _errs28 === errors;
                                } else {
                                  var valid2 = true;
                                }
                                if (valid2) {
                                  if (data1.app_key !== undefined) {
                                    let data10 = data1.app_key;
                                    const _errs34 = errors;
                                    const _errs35 = errors;
                                    let valid6 = false;
                                    const _errs36 = errors;
                                    if (typeof data10 !== "string") {
                                      const err9 = {
                                        instancePath: instancePath + "/data/app_key",
                                        schemaPath: "#/$defs/LogEntryResponse/properties/app_key/anyOf/0/type",
                                        keyword: "type",
                                        params: { type: "string" },
                                        message: "must be string",
                                      };
                                      if (vErrors === null) {
                                        vErrors = [err9];
                                      } else {
                                        vErrors.push(err9);
                                      }
                                      errors++;
                                    }
                                    var _valid3 = _errs36 === errors;
                                    valid6 = valid6 || _valid3;
                                    if (!valid6) {
                                      const _errs38 = errors;
                                      if (data10 !== null) {
                                        const err10 = {
                                          instancePath: instancePath + "/data/app_key",
                                          schemaPath: "#/$defs/LogEntryResponse/properties/app_key/anyOf/1/type",
                                          keyword: "type",
                                          params: { type: "null" },
                                          message: "must be null",
                                        };
                                        if (vErrors === null) {
                                          vErrors = [err10];
                                        } else {
                                          vErrors.push(err10);
                                        }
                                        errors++;
                                      }
                                      var _valid3 = _errs38 === errors;
                                      valid6 = valid6 || _valid3;
                                    }
                                    if (!valid6) {
                                      const err11 = {
                                        instancePath: instancePath + "/data/app_key",
                                        schemaPath: "#/$defs/LogEntryResponse/properties/app_key/anyOf",
                                        keyword: "anyOf",
                                        params: {},
                                        message: "must match a schema in anyOf",
                                      };
                                      if (vErrors === null) {
                                        vErrors = [err11];
                                      } else {
                                        vErrors.push(err11);
                                      }
                                      errors++;
                                      validate14.errors = vErrors;
                                      return false;
                                    } else {
                                      errors = _errs35;
                                      if (vErrors !== null) {
                                        if (_errs35) {
                                          vErrors.length = _errs35;
                                        } else {
                                          vErrors = null;
                                        }
                                      }
                                    }
                                    var valid2 = _errs34 === errors;
                                  } else {
                                    var valid2 = true;
                                  }
                                  if (valid2) {
                                    if (data1.execution_id !== undefined) {
                                      let data11 = data1.execution_id;
                                      const _errs40 = errors;
                                      const _errs41 = errors;
                                      let valid7 = false;
                                      const _errs42 = errors;
                                      if (typeof data11 !== "string") {
                                        const err12 = {
                                          instancePath: instancePath + "/data/execution_id",
                                          schemaPath: "#/$defs/LogEntryResponse/properties/execution_id/anyOf/0/type",
                                          keyword: "type",
                                          params: { type: "string" },
                                          message: "must be string",
                                        };
                                        if (vErrors === null) {
                                          vErrors = [err12];
                                        } else {
                                          vErrors.push(err12);
                                        }
                                        errors++;
                                      }
                                      var _valid4 = _errs42 === errors;
                                      valid7 = valid7 || _valid4;
                                      if (!valid7) {
                                        const _errs44 = errors;
                                        if (data11 !== null) {
                                          const err13 = {
                                            instancePath: instancePath + "/data/execution_id",
                                            schemaPath: "#/$defs/LogEntryResponse/properties/execution_id/anyOf/1/type",
                                            keyword: "type",
                                            params: { type: "null" },
                                            message: "must be null",
                                          };
                                          if (vErrors === null) {
                                            vErrors = [err13];
                                          } else {
                                            vErrors.push(err13);
                                          }
                                          errors++;
                                        }
                                        var _valid4 = _errs44 === errors;
                                        valid7 = valid7 || _valid4;
                                      }
                                      if (!valid7) {
                                        const err14 = {
                                          instancePath: instancePath + "/data/execution_id",
                                          schemaPath: "#/$defs/LogEntryResponse/properties/execution_id/anyOf",
                                          keyword: "anyOf",
                                          params: {},
                                          message: "must match a schema in anyOf",
                                        };
                                        if (vErrors === null) {
                                          vErrors = [err14];
                                        } else {
                                          vErrors.push(err14);
                                        }
                                        errors++;
                                        validate14.errors = vErrors;
                                        return false;
                                      } else {
                                        errors = _errs41;
                                        if (vErrors !== null) {
                                          if (_errs41) {
                                            vErrors.length = _errs41;
                                          } else {
                                            vErrors = null;
                                          }
                                        }
                                      }
                                      var valid2 = _errs40 === errors;
                                    } else {
                                      var valid2 = true;
                                    }
                                    if (valid2) {
                                      if (data1.instance_name !== undefined) {
                                        let data12 = data1.instance_name;
                                        const _errs46 = errors;
                                        const _errs47 = errors;
                                        let valid8 = false;
                                        const _errs48 = errors;
                                        if (typeof data12 !== "string") {
                                          const err15 = {
                                            instancePath: instancePath + "/data/instance_name",
                                            schemaPath:
                                              "#/$defs/LogEntryResponse/properties/instance_name/anyOf/0/type",
                                            keyword: "type",
                                            params: { type: "string" },
                                            message: "must be string",
                                          };
                                          if (vErrors === null) {
                                            vErrors = [err15];
                                          } else {
                                            vErrors.push(err15);
                                          }
                                          errors++;
                                        }
                                        var _valid5 = _errs48 === errors;
                                        valid8 = valid8 || _valid5;
                                        if (!valid8) {
                                          const _errs50 = errors;
                                          if (data12 !== null) {
                                            const err16 = {
                                              instancePath: instancePath + "/data/instance_name",
                                              schemaPath:
                                                "#/$defs/LogEntryResponse/properties/instance_name/anyOf/1/type",
                                              keyword: "type",
                                              params: { type: "null" },
                                              message: "must be null",
                                            };
                                            if (vErrors === null) {
                                              vErrors = [err16];
                                            } else {
                                              vErrors.push(err16);
                                            }
                                            errors++;
                                          }
                                          var _valid5 = _errs50 === errors;
                                          valid8 = valid8 || _valid5;
                                        }
                                        if (!valid8) {
                                          const err17 = {
                                            instancePath: instancePath + "/data/instance_name",
                                            schemaPath: "#/$defs/LogEntryResponse/properties/instance_name/anyOf",
                                            keyword: "anyOf",
                                            params: {},
                                            message: "must match a schema in anyOf",
                                          };
                                          if (vErrors === null) {
                                            vErrors = [err17];
                                          } else {
                                            vErrors.push(err17);
                                          }
                                          errors++;
                                          validate14.errors = vErrors;
                                          return false;
                                        } else {
                                          errors = _errs47;
                                          if (vErrors !== null) {
                                            if (_errs47) {
                                              vErrors.length = _errs47;
                                            } else {
                                              vErrors = null;
                                            }
                                          }
                                        }
                                        var valid2 = _errs46 === errors;
                                      } else {
                                        var valid2 = true;
                                      }
                                      if (valid2) {
                                        if (data1.instance_index !== undefined) {
                                          let data13 = data1.instance_index;
                                          const _errs52 = errors;
                                          const _errs53 = errors;
                                          let valid9 = false;
                                          const _errs54 = errors;
                                          if (!(typeof data13 == "number" && !(data13 % 1) && !isNaN(data13))) {
                                            const err18 = {
                                              instancePath: instancePath + "/data/instance_index",
                                              schemaPath:
                                                "#/$defs/LogEntryResponse/properties/instance_index/anyOf/0/type",
                                              keyword: "type",
                                              params: { type: "integer" },
                                              message: "must be integer",
                                            };
                                            if (vErrors === null) {
                                              vErrors = [err18];
                                            } else {
                                              vErrors.push(err18);
                                            }
                                            errors++;
                                          }
                                          var _valid6 = _errs54 === errors;
                                          valid9 = valid9 || _valid6;
                                          if (!valid9) {
                                            const _errs56 = errors;
                                            if (data13 !== null) {
                                              const err19 = {
                                                instancePath: instancePath + "/data/instance_index",
                                                schemaPath:
                                                  "#/$defs/LogEntryResponse/properties/instance_index/anyOf/1/type",
                                                keyword: "type",
                                                params: { type: "null" },
                                                message: "must be null",
                                              };
                                              if (vErrors === null) {
                                                vErrors = [err19];
                                              } else {
                                                vErrors.push(err19);
                                              }
                                              errors++;
                                            }
                                            var _valid6 = _errs56 === errors;
                                            valid9 = valid9 || _valid6;
                                          }
                                          if (!valid9) {
                                            const err20 = {
                                              instancePath: instancePath + "/data/instance_index",
                                              schemaPath: "#/$defs/LogEntryResponse/properties/instance_index/anyOf",
                                              keyword: "anyOf",
                                              params: {},
                                              message: "must match a schema in anyOf",
                                            };
                                            if (vErrors === null) {
                                              vErrors = [err20];
                                            } else {
                                              vErrors.push(err20);
                                            }
                                            errors++;
                                            validate14.errors = vErrors;
                                            return false;
                                          } else {
                                            errors = _errs53;
                                            if (vErrors !== null) {
                                              if (_errs53) {
                                                vErrors.length = _errs53;
                                              } else {
                                                vErrors = null;
                                              }
                                            }
                                          }
                                          var valid2 = _errs52 === errors;
                                        } else {
                                          var valid2 = true;
                                        }
                                        if (valid2) {
                                          if (data1.source_tier !== undefined) {
                                            let data14 = data1.source_tier;
                                            const _errs58 = errors;
                                            const _errs59 = errors;
                                            let valid10 = false;
                                            const _errs60 = errors;
                                            if (typeof data14 !== "string") {
                                              const err21 = {
                                                instancePath: instancePath + "/data/source_tier",
                                                schemaPath:
                                                  "#/$defs/LogEntryResponse/properties/source_tier/anyOf/0/type",
                                                keyword: "type",
                                                params: { type: "string" },
                                                message: "must be string",
                                              };
                                              if (vErrors === null) {
                                                vErrors = [err21];
                                              } else {
                                                vErrors.push(err21);
                                              }
                                              errors++;
                                            }
                                            if (!(data14 === "app" || data14 === "framework")) {
                                              const err22 = {
                                                instancePath: instancePath + "/data/source_tier",
                                                schemaPath:
                                                  "#/$defs/LogEntryResponse/properties/source_tier/anyOf/0/enum",
                                                keyword: "enum",
                                                params: {
                                                  allowedValues: schema17.properties.source_tier.anyOf[0].enum,
                                                },
                                                message: "must be equal to one of the allowed values",
                                              };
                                              if (vErrors === null) {
                                                vErrors = [err22];
                                              } else {
                                                vErrors.push(err22);
                                              }
                                              errors++;
                                            }
                                            var _valid7 = _errs60 === errors;
                                            valid10 = valid10 || _valid7;
                                            if (!valid10) {
                                              const _errs62 = errors;
                                              if (data14 !== null) {
                                                const err23 = {
                                                  instancePath: instancePath + "/data/source_tier",
                                                  schemaPath:
                                                    "#/$defs/LogEntryResponse/properties/source_tier/anyOf/1/type",
                                                  keyword: "type",
                                                  params: { type: "null" },
                                                  message: "must be null",
                                                };
                                                if (vErrors === null) {
                                                  vErrors = [err23];
                                                } else {
                                                  vErrors.push(err23);
                                                }
                                                errors++;
                                              }
                                              var _valid7 = _errs62 === errors;
                                              valid10 = valid10 || _valid7;
                                            }
                                            if (!valid10) {
                                              const err24 = {
                                                instancePath: instancePath + "/data/source_tier",
                                                schemaPath: "#/$defs/LogEntryResponse/properties/source_tier/anyOf",
                                                keyword: "anyOf",
                                                params: {},
                                                message: "must match a schema in anyOf",
                                              };
                                              if (vErrors === null) {
                                                vErrors = [err24];
                                              } else {
                                                vErrors.push(err24);
                                              }
                                              errors++;
                                              validate14.errors = vErrors;
                                              return false;
                                            } else {
                                              errors = _errs59;
                                              if (vErrors !== null) {
                                                if (_errs59) {
                                                  vErrors.length = _errs59;
                                                } else {
                                                  vErrors = null;
                                                }
                                              }
                                            }
                                            var valid2 = _errs58 === errors;
                                          } else {
                                            var valid2 = true;
                                          }
                                          if (valid2) {
                                            if (data1.execution_kind !== undefined) {
                                              let data15 = data1.execution_kind;
                                              const _errs64 = errors;
                                              const _errs65 = errors;
                                              let valid11 = false;
                                              const _errs66 = errors;
                                              if (typeof data15 !== "string") {
                                                const err25 = {
                                                  instancePath: instancePath + "/data/execution_kind",
                                                  schemaPath:
                                                    "#/$defs/LogEntryResponse/properties/execution_kind/anyOf/0/type",
                                                  keyword: "type",
                                                  params: { type: "string" },
                                                  message: "must be string",
                                                };
                                                if (vErrors === null) {
                                                  vErrors = [err25];
                                                } else {
                                                  vErrors.push(err25);
                                                }
                                                errors++;
                                              }
                                              if (!(data15 === "handler" || data15 === "job")) {
                                                const err26 = {
                                                  instancePath: instancePath + "/data/execution_kind",
                                                  schemaPath:
                                                    "#/$defs/LogEntryResponse/properties/execution_kind/anyOf/0/enum",
                                                  keyword: "enum",
                                                  params: {
                                                    allowedValues: schema17.properties.execution_kind.anyOf[0].enum,
                                                  },
                                                  message: "must be equal to one of the allowed values",
                                                };
                                                if (vErrors === null) {
                                                  vErrors = [err26];
                                                } else {
                                                  vErrors.push(err26);
                                                }
                                                errors++;
                                              }
                                              var _valid8 = _errs66 === errors;
                                              valid11 = valid11 || _valid8;
                                              if (!valid11) {
                                                const _errs68 = errors;
                                                if (data15 !== null) {
                                                  const err27 = {
                                                    instancePath: instancePath + "/data/execution_kind",
                                                    schemaPath:
                                                      "#/$defs/LogEntryResponse/properties/execution_kind/anyOf/1/type",
                                                    keyword: "type",
                                                    params: { type: "null" },
                                                    message: "must be null",
                                                  };
                                                  if (vErrors === null) {
                                                    vErrors = [err27];
                                                  } else {
                                                    vErrors.push(err27);
                                                  }
                                                  errors++;
                                                }
                                                var _valid8 = _errs68 === errors;
                                                valid11 = valid11 || _valid8;
                                              }
                                              if (!valid11) {
                                                const err28 = {
                                                  instancePath: instancePath + "/data/execution_kind",
                                                  schemaPath:
                                                    "#/$defs/LogEntryResponse/properties/execution_kind/anyOf",
                                                  keyword: "anyOf",
                                                  params: {},
                                                  message: "must match a schema in anyOf",
                                                };
                                                if (vErrors === null) {
                                                  vErrors = [err28];
                                                } else {
                                                  vErrors.push(err28);
                                                }
                                                errors++;
                                                validate14.errors = vErrors;
                                                return false;
                                              } else {
                                                errors = _errs65;
                                                if (vErrors !== null) {
                                                  if (_errs65) {
                                                    vErrors.length = _errs65;
                                                  } else {
                                                    vErrors = null;
                                                  }
                                                }
                                              }
                                              var valid2 = _errs64 === errors;
                                            } else {
                                              var valid2 = true;
                                            }
                                            if (valid2) {
                                              if (data1.listener_id !== undefined) {
                                                let data16 = data1.listener_id;
                                                const _errs70 = errors;
                                                const _errs71 = errors;
                                                let valid12 = false;
                                                const _errs72 = errors;
                                                if (!(typeof data16 == "number" && !(data16 % 1) && !isNaN(data16))) {
                                                  const err29 = {
                                                    instancePath: instancePath + "/data/listener_id",
                                                    schemaPath:
                                                      "#/$defs/LogEntryResponse/properties/listener_id/anyOf/0/type",
                                                    keyword: "type",
                                                    params: { type: "integer" },
                                                    message: "must be integer",
                                                  };
                                                  if (vErrors === null) {
                                                    vErrors = [err29];
                                                  } else {
                                                    vErrors.push(err29);
                                                  }
                                                  errors++;
                                                }
                                                var _valid9 = _errs72 === errors;
                                                valid12 = valid12 || _valid9;
                                                if (!valid12) {
                                                  const _errs74 = errors;
                                                  if (data16 !== null) {
                                                    const err30 = {
                                                      instancePath: instancePath + "/data/listener_id",
                                                      schemaPath:
                                                        "#/$defs/LogEntryResponse/properties/listener_id/anyOf/1/type",
                                                      keyword: "type",
                                                      params: { type: "null" },
                                                      message: "must be null",
                                                    };
                                                    if (vErrors === null) {
                                                      vErrors = [err30];
                                                    } else {
                                                      vErrors.push(err30);
                                                    }
                                                    errors++;
                                                  }
                                                  var _valid9 = _errs74 === errors;
                                                  valid12 = valid12 || _valid9;
                                                }
                                                if (!valid12) {
                                                  const err31 = {
                                                    instancePath: instancePath + "/data/listener_id",
                                                    schemaPath: "#/$defs/LogEntryResponse/properties/listener_id/anyOf",
                                                    keyword: "anyOf",
                                                    params: {},
                                                    message: "must match a schema in anyOf",
                                                  };
                                                  if (vErrors === null) {
                                                    vErrors = [err31];
                                                  } else {
                                                    vErrors.push(err31);
                                                  }
                                                  errors++;
                                                  validate14.errors = vErrors;
                                                  return false;
                                                } else {
                                                  errors = _errs71;
                                                  if (vErrors !== null) {
                                                    if (_errs71) {
                                                      vErrors.length = _errs71;
                                                    } else {
                                                      vErrors = null;
                                                    }
                                                  }
                                                }
                                                var valid2 = _errs70 === errors;
                                              } else {
                                                var valid2 = true;
                                              }
                                              if (valid2) {
                                                if (data1.job_id !== undefined) {
                                                  let data17 = data1.job_id;
                                                  const _errs76 = errors;
                                                  const _errs77 = errors;
                                                  let valid13 = false;
                                                  const _errs78 = errors;
                                                  if (!(typeof data17 == "number" && !(data17 % 1) && !isNaN(data17))) {
                                                    const err32 = {
                                                      instancePath: instancePath + "/data/job_id",
                                                      schemaPath:
                                                        "#/$defs/LogEntryResponse/properties/job_id/anyOf/0/type",
                                                      keyword: "type",
                                                      params: { type: "integer" },
                                                      message: "must be integer",
                                                    };
                                                    if (vErrors === null) {
                                                      vErrors = [err32];
                                                    } else {
                                                      vErrors.push(err32);
                                                    }
                                                    errors++;
                                                  }
                                                  var _valid10 = _errs78 === errors;
                                                  valid13 = valid13 || _valid10;
                                                  if (!valid13) {
                                                    const _errs80 = errors;
                                                    if (data17 !== null) {
                                                      const err33 = {
                                                        instancePath: instancePath + "/data/job_id",
                                                        schemaPath:
                                                          "#/$defs/LogEntryResponse/properties/job_id/anyOf/1/type",
                                                        keyword: "type",
                                                        params: { type: "null" },
                                                        message: "must be null",
                                                      };
                                                      if (vErrors === null) {
                                                        vErrors = [err33];
                                                      } else {
                                                        vErrors.push(err33);
                                                      }
                                                      errors++;
                                                    }
                                                    var _valid10 = _errs80 === errors;
                                                    valid13 = valid13 || _valid10;
                                                  }
                                                  if (!valid13) {
                                                    const err34 = {
                                                      instancePath: instancePath + "/data/job_id",
                                                      schemaPath: "#/$defs/LogEntryResponse/properties/job_id/anyOf",
                                                      keyword: "anyOf",
                                                      params: {},
                                                      message: "must match a schema in anyOf",
                                                    };
                                                    if (vErrors === null) {
                                                      vErrors = [err34];
                                                    } else {
                                                      vErrors.push(err34);
                                                    }
                                                    errors++;
                                                    validate14.errors = vErrors;
                                                    return false;
                                                  } else {
                                                    errors = _errs77;
                                                    if (vErrors !== null) {
                                                      if (_errs77) {
                                                        vErrors.length = _errs77;
                                                      } else {
                                                        vErrors = null;
                                                      }
                                                    }
                                                  }
                                                  var valid2 = _errs76 === errors;
                                                } else {
                                                  var valid2 = true;
                                                }
                                              }
                                            }
                                          }
                                        }
                                      }
                                    }
                                  }
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              } else {
                validate14.errors = [
                  {
                    instancePath: instancePath + "/data",
                    schemaPath: "#/$defs/LogEntryResponse/type",
                    keyword: "type",
                    params: { type: "object" },
                    message: "must be object",
                  },
                ];
                return false;
              }
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.timestamp !== undefined) {
              const _errs82 = errors;
              if (!(typeof data.timestamp == "number")) {
                validate14.errors = [
                  {
                    instancePath: instancePath + "/timestamp",
                    schemaPath: "#/properties/timestamp/type",
                    keyword: "type",
                    params: { type: "number" },
                    message: "must be number",
                  },
                ];
                return false;
              }
              var valid0 = _errs82 === errors;
            } else {
              var valid0 = true;
            }
          }
        }
      }
    } else {
      validate14.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate14.errors = vErrors;
  return errors === 0;
}
const schema18 = {
  properties: {
    type: { const: "connected", title: "Type", type: "string" },
    data: { $ref: "#/$defs/ConnectedPayload" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "ConnectedWsMessage",
  type: "object",
};
const schema19 = {
  properties: {
    uptime_seconds: { title: "Uptime Seconds", type: "number" },
    entity_count: { title: "Entity Count", type: "integer" },
    app_count: { title: "App Count", type: "integer" },
    version: { default: "", title: "Version", type: "string" },
  },
  required: ["uptime_seconds", "entity_count", "app_count"],
  title: "ConnectedPayload",
  type: "object",
};
function validate15(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.type === undefined && (missing0 = "type")) ||
        (data.data === undefined && (missing0 = "data")) ||
        (data.timestamp === undefined && (missing0 = "timestamp"))
      ) {
        validate15.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.type !== undefined) {
          let data0 = data.type;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate15.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          if ("connected" !== data0) {
            validate15.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "connected" },
                message: "must be equal to constant",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.data !== undefined) {
            let data1 = data.data;
            const _errs3 = errors;
            const _errs4 = errors;
            if (errors === _errs4) {
              if (data1 && typeof data1 == "object" && !Array.isArray(data1)) {
                let missing1;
                if (
                  (data1.uptime_seconds === undefined && (missing1 = "uptime_seconds")) ||
                  (data1.entity_count === undefined && (missing1 = "entity_count")) ||
                  (data1.app_count === undefined && (missing1 = "app_count"))
                ) {
                  validate15.errors = [
                    {
                      instancePath: instancePath + "/data",
                      schemaPath: "#/$defs/ConnectedPayload/required",
                      keyword: "required",
                      params: { missingProperty: missing1 },
                      message: "must have required property '" + missing1 + "'",
                    },
                  ];
                  return false;
                } else {
                  if (data1.uptime_seconds !== undefined) {
                    const _errs6 = errors;
                    if (!(typeof data1.uptime_seconds == "number")) {
                      validate15.errors = [
                        {
                          instancePath: instancePath + "/data/uptime_seconds",
                          schemaPath: "#/$defs/ConnectedPayload/properties/uptime_seconds/type",
                          keyword: "type",
                          params: { type: "number" },
                          message: "must be number",
                        },
                      ];
                      return false;
                    }
                    var valid2 = _errs6 === errors;
                  } else {
                    var valid2 = true;
                  }
                  if (valid2) {
                    if (data1.entity_count !== undefined) {
                      let data3 = data1.entity_count;
                      const _errs8 = errors;
                      if (!(typeof data3 == "number" && !(data3 % 1) && !isNaN(data3))) {
                        validate15.errors = [
                          {
                            instancePath: instancePath + "/data/entity_count",
                            schemaPath: "#/$defs/ConnectedPayload/properties/entity_count/type",
                            keyword: "type",
                            params: { type: "integer" },
                            message: "must be integer",
                          },
                        ];
                        return false;
                      }
                      var valid2 = _errs8 === errors;
                    } else {
                      var valid2 = true;
                    }
                    if (valid2) {
                      if (data1.app_count !== undefined) {
                        let data4 = data1.app_count;
                        const _errs10 = errors;
                        if (!(typeof data4 == "number" && !(data4 % 1) && !isNaN(data4))) {
                          validate15.errors = [
                            {
                              instancePath: instancePath + "/data/app_count",
                              schemaPath: "#/$defs/ConnectedPayload/properties/app_count/type",
                              keyword: "type",
                              params: { type: "integer" },
                              message: "must be integer",
                            },
                          ];
                          return false;
                        }
                        var valid2 = _errs10 === errors;
                      } else {
                        var valid2 = true;
                      }
                      if (valid2) {
                        if (data1.version !== undefined) {
                          const _errs12 = errors;
                          if (typeof data1.version !== "string") {
                            validate15.errors = [
                              {
                                instancePath: instancePath + "/data/version",
                                schemaPath: "#/$defs/ConnectedPayload/properties/version/type",
                                keyword: "type",
                                params: { type: "string" },
                                message: "must be string",
                              },
                            ];
                            return false;
                          }
                          var valid2 = _errs12 === errors;
                        } else {
                          var valid2 = true;
                        }
                      }
                    }
                  }
                }
              } else {
                validate15.errors = [
                  {
                    instancePath: instancePath + "/data",
                    schemaPath: "#/$defs/ConnectedPayload/type",
                    keyword: "type",
                    params: { type: "object" },
                    message: "must be object",
                  },
                ];
                return false;
              }
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.timestamp !== undefined) {
              const _errs14 = errors;
              if (!(typeof data.timestamp == "number")) {
                validate15.errors = [
                  {
                    instancePath: instancePath + "/timestamp",
                    schemaPath: "#/properties/timestamp/type",
                    keyword: "type",
                    params: { type: "number" },
                    message: "must be number",
                  },
                ];
                return false;
              }
              var valid0 = _errs14 === errors;
            } else {
              var valid0 = true;
            }
          }
        }
      }
    } else {
      validate15.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate15.errors = vErrors;
  return errors === 0;
}
const schema20 = {
  properties: {
    type: { const: "connectivity", title: "Type", type: "string" },
    data: { $ref: "#/$defs/ConnectivityData" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "ConnectivityWsMessage",
  type: "object",
};
const schema21 = {
  description: "Payload for a Home Assistant WebSocket connectivity event.",
  properties: { connected: { title: "Connected", type: "boolean" } },
  required: ["connected"],
  title: "ConnectivityData",
  type: "object",
};
function validate16(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.type === undefined && (missing0 = "type")) ||
        (data.data === undefined && (missing0 = "data")) ||
        (data.timestamp === undefined && (missing0 = "timestamp"))
      ) {
        validate16.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.type !== undefined) {
          let data0 = data.type;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate16.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          if ("connectivity" !== data0) {
            validate16.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "connectivity" },
                message: "must be equal to constant",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.data !== undefined) {
            let data1 = data.data;
            const _errs3 = errors;
            const _errs4 = errors;
            if (errors === _errs4) {
              if (data1 && typeof data1 == "object" && !Array.isArray(data1)) {
                let missing1;
                if (data1.connected === undefined && (missing1 = "connected")) {
                  validate16.errors = [
                    {
                      instancePath: instancePath + "/data",
                      schemaPath: "#/$defs/ConnectivityData/required",
                      keyword: "required",
                      params: { missingProperty: missing1 },
                      message: "must have required property '" + missing1 + "'",
                    },
                  ];
                  return false;
                } else {
                  if (data1.connected !== undefined) {
                    if (typeof data1.connected !== "boolean") {
                      validate16.errors = [
                        {
                          instancePath: instancePath + "/data/connected",
                          schemaPath: "#/$defs/ConnectivityData/properties/connected/type",
                          keyword: "type",
                          params: { type: "boolean" },
                          message: "must be boolean",
                        },
                      ];
                      return false;
                    }
                  }
                }
              } else {
                validate16.errors = [
                  {
                    instancePath: instancePath + "/data",
                    schemaPath: "#/$defs/ConnectivityData/type",
                    keyword: "type",
                    params: { type: "object" },
                    message: "must be object",
                  },
                ];
                return false;
              }
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.timestamp !== undefined) {
              const _errs8 = errors;
              if (!(typeof data.timestamp == "number")) {
                validate16.errors = [
                  {
                    instancePath: instancePath + "/timestamp",
                    schemaPath: "#/properties/timestamp/type",
                    keyword: "type",
                    params: { type: "number" },
                    message: "must be number",
                  },
                ];
                return false;
              }
              var valid0 = _errs8 === errors;
            } else {
              var valid0 = true;
            }
          }
        }
      }
    } else {
      validate16.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate16.errors = vErrors;
  return errors === 0;
}
const schema22 = {
  properties: {
    type: { const: "service_status", title: "Type", type: "string" },
    data: { $ref: "#/$defs/ServiceStatusData" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "ServiceStatusWsMessage",
  type: "object",
};
const schema23 = {
  description:
    "Payload for an internal service status-change event broadcast over WebSocket.\n\nMirrors ``events.hassette.ServiceStatusPayload``.",
  properties: {
    resource_name: { title: "Resource Name", type: "string" },
    role: { title: "Role", type: "string" },
    status: { $ref: "#/$defs/ResourceStatus" },
    previous_status: { anyOf: [{ $ref: "#/$defs/ResourceStatus" }, { type: "null" }], default: null },
    exception: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception" },
    exception_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Type" },
    exception_traceback: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Traceback" },
    retry_at: { anyOf: [{ type: "number" }, { type: "null" }], default: null, title: "Retry At" },
    ready: { default: false, title: "Ready", type: "boolean" },
    ready_phase: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Ready Phase" },
  },
  required: ["resource_name", "role", "status"],
  title: "ServiceStatusData",
  type: "object",
};
function validate18(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.resource_name === undefined && (missing0 = "resource_name")) ||
        (data.role === undefined && (missing0 = "role")) ||
        (data.status === undefined && (missing0 = "status"))
      ) {
        validate18.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.resource_name !== undefined) {
          const _errs1 = errors;
          if (typeof data.resource_name !== "string") {
            validate18.errors = [
              {
                instancePath: instancePath + "/resource_name",
                schemaPath: "#/properties/resource_name/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.role !== undefined) {
            const _errs3 = errors;
            if (typeof data.role !== "string") {
              validate18.errors = [
                {
                  instancePath: instancePath + "/role",
                  schemaPath: "#/properties/role/type",
                  keyword: "type",
                  params: { type: "string" },
                  message: "must be string",
                },
              ];
              return false;
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.status !== undefined) {
              let data2 = data.status;
              const _errs5 = errors;
              if (typeof data2 !== "string") {
                validate18.errors = [
                  {
                    instancePath: instancePath + "/status",
                    schemaPath: "#/$defs/ResourceStatus/type",
                    keyword: "type",
                    params: { type: "string" },
                    message: "must be string",
                  },
                ];
                return false;
              }
              if (!(
                data2 === "not_started" ||
                data2 === "starting" ||
                data2 === "running" ||
                data2 === "stopping" ||
                data2 === "stopped" ||
                data2 === "failed" ||
                data2 === "crashed" ||
                data2 === "exhausted_dead" ||
                data2 === "exhausted_cooling"
              )) {
                validate18.errors = [
                  {
                    instancePath: instancePath + "/status",
                    schemaPath: "#/$defs/ResourceStatus/enum",
                    keyword: "enum",
                    params: { allowedValues: schema14.enum },
                    message: "must be equal to one of the allowed values",
                  },
                ];
                return false;
              }
              var valid0 = _errs5 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.previous_status !== undefined) {
                let data3 = data.previous_status;
                const _errs8 = errors;
                const _errs9 = errors;
                let valid2 = false;
                const _errs10 = errors;
                if (typeof data3 !== "string") {
                  const err0 = {
                    instancePath: instancePath + "/previous_status",
                    schemaPath: "#/$defs/ResourceStatus/type",
                    keyword: "type",
                    params: { type: "string" },
                    message: "must be string",
                  };
                  if (vErrors === null) {
                    vErrors = [err0];
                  } else {
                    vErrors.push(err0);
                  }
                  errors++;
                }
                if (!(
                  data3 === "not_started" ||
                  data3 === "starting" ||
                  data3 === "running" ||
                  data3 === "stopping" ||
                  data3 === "stopped" ||
                  data3 === "failed" ||
                  data3 === "crashed" ||
                  data3 === "exhausted_dead" ||
                  data3 === "exhausted_cooling"
                )) {
                  const err1 = {
                    instancePath: instancePath + "/previous_status",
                    schemaPath: "#/$defs/ResourceStatus/enum",
                    keyword: "enum",
                    params: { allowedValues: schema14.enum },
                    message: "must be equal to one of the allowed values",
                  };
                  if (vErrors === null) {
                    vErrors = [err1];
                  } else {
                    vErrors.push(err1);
                  }
                  errors++;
                }
                var _valid0 = _errs10 === errors;
                valid2 = valid2 || _valid0;
                if (!valid2) {
                  const _errs13 = errors;
                  if (data3 !== null) {
                    const err2 = {
                      instancePath: instancePath + "/previous_status",
                      schemaPath: "#/properties/previous_status/anyOf/1/type",
                      keyword: "type",
                      params: { type: "null" },
                      message: "must be null",
                    };
                    if (vErrors === null) {
                      vErrors = [err2];
                    } else {
                      vErrors.push(err2);
                    }
                    errors++;
                  }
                  var _valid0 = _errs13 === errors;
                  valid2 = valid2 || _valid0;
                }
                if (!valid2) {
                  const err3 = {
                    instancePath: instancePath + "/previous_status",
                    schemaPath: "#/properties/previous_status/anyOf",
                    keyword: "anyOf",
                    params: {},
                    message: "must match a schema in anyOf",
                  };
                  if (vErrors === null) {
                    vErrors = [err3];
                  } else {
                    vErrors.push(err3);
                  }
                  errors++;
                  validate18.errors = vErrors;
                  return false;
                } else {
                  errors = _errs9;
                  if (vErrors !== null) {
                    if (_errs9) {
                      vErrors.length = _errs9;
                    } else {
                      vErrors = null;
                    }
                  }
                }
                var valid0 = _errs8 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.exception !== undefined) {
                  let data4 = data.exception;
                  const _errs15 = errors;
                  const _errs16 = errors;
                  let valid4 = false;
                  const _errs17 = errors;
                  if (typeof data4 !== "string") {
                    const err4 = {
                      instancePath: instancePath + "/exception",
                      schemaPath: "#/properties/exception/anyOf/0/type",
                      keyword: "type",
                      params: { type: "string" },
                      message: "must be string",
                    };
                    if (vErrors === null) {
                      vErrors = [err4];
                    } else {
                      vErrors.push(err4);
                    }
                    errors++;
                  }
                  var _valid1 = _errs17 === errors;
                  valid4 = valid4 || _valid1;
                  if (!valid4) {
                    const _errs19 = errors;
                    if (data4 !== null) {
                      const err5 = {
                        instancePath: instancePath + "/exception",
                        schemaPath: "#/properties/exception/anyOf/1/type",
                        keyword: "type",
                        params: { type: "null" },
                        message: "must be null",
                      };
                      if (vErrors === null) {
                        vErrors = [err5];
                      } else {
                        vErrors.push(err5);
                      }
                      errors++;
                    }
                    var _valid1 = _errs19 === errors;
                    valid4 = valid4 || _valid1;
                  }
                  if (!valid4) {
                    const err6 = {
                      instancePath: instancePath + "/exception",
                      schemaPath: "#/properties/exception/anyOf",
                      keyword: "anyOf",
                      params: {},
                      message: "must match a schema in anyOf",
                    };
                    if (vErrors === null) {
                      vErrors = [err6];
                    } else {
                      vErrors.push(err6);
                    }
                    errors++;
                    validate18.errors = vErrors;
                    return false;
                  } else {
                    errors = _errs16;
                    if (vErrors !== null) {
                      if (_errs16) {
                        vErrors.length = _errs16;
                      } else {
                        vErrors = null;
                      }
                    }
                  }
                  var valid0 = _errs15 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.exception_type !== undefined) {
                    let data5 = data.exception_type;
                    const _errs21 = errors;
                    const _errs22 = errors;
                    let valid5 = false;
                    const _errs23 = errors;
                    if (typeof data5 !== "string") {
                      const err7 = {
                        instancePath: instancePath + "/exception_type",
                        schemaPath: "#/properties/exception_type/anyOf/0/type",
                        keyword: "type",
                        params: { type: "string" },
                        message: "must be string",
                      };
                      if (vErrors === null) {
                        vErrors = [err7];
                      } else {
                        vErrors.push(err7);
                      }
                      errors++;
                    }
                    var _valid2 = _errs23 === errors;
                    valid5 = valid5 || _valid2;
                    if (!valid5) {
                      const _errs25 = errors;
                      if (data5 !== null) {
                        const err8 = {
                          instancePath: instancePath + "/exception_type",
                          schemaPath: "#/properties/exception_type/anyOf/1/type",
                          keyword: "type",
                          params: { type: "null" },
                          message: "must be null",
                        };
                        if (vErrors === null) {
                          vErrors = [err8];
                        } else {
                          vErrors.push(err8);
                        }
                        errors++;
                      }
                      var _valid2 = _errs25 === errors;
                      valid5 = valid5 || _valid2;
                    }
                    if (!valid5) {
                      const err9 = {
                        instancePath: instancePath + "/exception_type",
                        schemaPath: "#/properties/exception_type/anyOf",
                        keyword: "anyOf",
                        params: {},
                        message: "must match a schema in anyOf",
                      };
                      if (vErrors === null) {
                        vErrors = [err9];
                      } else {
                        vErrors.push(err9);
                      }
                      errors++;
                      validate18.errors = vErrors;
                      return false;
                    } else {
                      errors = _errs22;
                      if (vErrors !== null) {
                        if (_errs22) {
                          vErrors.length = _errs22;
                        } else {
                          vErrors = null;
                        }
                      }
                    }
                    var valid0 = _errs21 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.exception_traceback !== undefined) {
                      let data6 = data.exception_traceback;
                      const _errs27 = errors;
                      const _errs28 = errors;
                      let valid6 = false;
                      const _errs29 = errors;
                      if (typeof data6 !== "string") {
                        const err10 = {
                          instancePath: instancePath + "/exception_traceback",
                          schemaPath: "#/properties/exception_traceback/anyOf/0/type",
                          keyword: "type",
                          params: { type: "string" },
                          message: "must be string",
                        };
                        if (vErrors === null) {
                          vErrors = [err10];
                        } else {
                          vErrors.push(err10);
                        }
                        errors++;
                      }
                      var _valid3 = _errs29 === errors;
                      valid6 = valid6 || _valid3;
                      if (!valid6) {
                        const _errs31 = errors;
                        if (data6 !== null) {
                          const err11 = {
                            instancePath: instancePath + "/exception_traceback",
                            schemaPath: "#/properties/exception_traceback/anyOf/1/type",
                            keyword: "type",
                            params: { type: "null" },
                            message: "must be null",
                          };
                          if (vErrors === null) {
                            vErrors = [err11];
                          } else {
                            vErrors.push(err11);
                          }
                          errors++;
                        }
                        var _valid3 = _errs31 === errors;
                        valid6 = valid6 || _valid3;
                      }
                      if (!valid6) {
                        const err12 = {
                          instancePath: instancePath + "/exception_traceback",
                          schemaPath: "#/properties/exception_traceback/anyOf",
                          keyword: "anyOf",
                          params: {},
                          message: "must match a schema in anyOf",
                        };
                        if (vErrors === null) {
                          vErrors = [err12];
                        } else {
                          vErrors.push(err12);
                        }
                        errors++;
                        validate18.errors = vErrors;
                        return false;
                      } else {
                        errors = _errs28;
                        if (vErrors !== null) {
                          if (_errs28) {
                            vErrors.length = _errs28;
                          } else {
                            vErrors = null;
                          }
                        }
                      }
                      var valid0 = _errs27 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.retry_at !== undefined) {
                        let data7 = data.retry_at;
                        const _errs33 = errors;
                        const _errs34 = errors;
                        let valid7 = false;
                        const _errs35 = errors;
                        if (!(typeof data7 == "number")) {
                          const err13 = {
                            instancePath: instancePath + "/retry_at",
                            schemaPath: "#/properties/retry_at/anyOf/0/type",
                            keyword: "type",
                            params: { type: "number" },
                            message: "must be number",
                          };
                          if (vErrors === null) {
                            vErrors = [err13];
                          } else {
                            vErrors.push(err13);
                          }
                          errors++;
                        }
                        var _valid4 = _errs35 === errors;
                        valid7 = valid7 || _valid4;
                        if (!valid7) {
                          const _errs37 = errors;
                          if (data7 !== null) {
                            const err14 = {
                              instancePath: instancePath + "/retry_at",
                              schemaPath: "#/properties/retry_at/anyOf/1/type",
                              keyword: "type",
                              params: { type: "null" },
                              message: "must be null",
                            };
                            if (vErrors === null) {
                              vErrors = [err14];
                            } else {
                              vErrors.push(err14);
                            }
                            errors++;
                          }
                          var _valid4 = _errs37 === errors;
                          valid7 = valid7 || _valid4;
                        }
                        if (!valid7) {
                          const err15 = {
                            instancePath: instancePath + "/retry_at",
                            schemaPath: "#/properties/retry_at/anyOf",
                            keyword: "anyOf",
                            params: {},
                            message: "must match a schema in anyOf",
                          };
                          if (vErrors === null) {
                            vErrors = [err15];
                          } else {
                            vErrors.push(err15);
                          }
                          errors++;
                          validate18.errors = vErrors;
                          return false;
                        } else {
                          errors = _errs34;
                          if (vErrors !== null) {
                            if (_errs34) {
                              vErrors.length = _errs34;
                            } else {
                              vErrors = null;
                            }
                          }
                        }
                        var valid0 = _errs33 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.ready !== undefined) {
                          const _errs39 = errors;
                          if (typeof data.ready !== "boolean") {
                            validate18.errors = [
                              {
                                instancePath: instancePath + "/ready",
                                schemaPath: "#/properties/ready/type",
                                keyword: "type",
                                params: { type: "boolean" },
                                message: "must be boolean",
                              },
                            ];
                            return false;
                          }
                          var valid0 = _errs39 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.ready_phase !== undefined) {
                            let data9 = data.ready_phase;
                            const _errs41 = errors;
                            const _errs42 = errors;
                            let valid8 = false;
                            const _errs43 = errors;
                            if (typeof data9 !== "string") {
                              const err16 = {
                                instancePath: instancePath + "/ready_phase",
                                schemaPath: "#/properties/ready_phase/anyOf/0/type",
                                keyword: "type",
                                params: { type: "string" },
                                message: "must be string",
                              };
                              if (vErrors === null) {
                                vErrors = [err16];
                              } else {
                                vErrors.push(err16);
                              }
                              errors++;
                            }
                            var _valid5 = _errs43 === errors;
                            valid8 = valid8 || _valid5;
                            if (!valid8) {
                              const _errs45 = errors;
                              if (data9 !== null) {
                                const err17 = {
                                  instancePath: instancePath + "/ready_phase",
                                  schemaPath: "#/properties/ready_phase/anyOf/1/type",
                                  keyword: "type",
                                  params: { type: "null" },
                                  message: "must be null",
                                };
                                if (vErrors === null) {
                                  vErrors = [err17];
                                } else {
                                  vErrors.push(err17);
                                }
                                errors++;
                              }
                              var _valid5 = _errs45 === errors;
                              valid8 = valid8 || _valid5;
                            }
                            if (!valid8) {
                              const err18 = {
                                instancePath: instancePath + "/ready_phase",
                                schemaPath: "#/properties/ready_phase/anyOf",
                                keyword: "anyOf",
                                params: {},
                                message: "must match a schema in anyOf",
                              };
                              if (vErrors === null) {
                                vErrors = [err18];
                              } else {
                                vErrors.push(err18);
                              }
                              errors++;
                              validate18.errors = vErrors;
                              return false;
                            } else {
                              errors = _errs42;
                              if (vErrors !== null) {
                                if (_errs42) {
                                  vErrors.length = _errs42;
                                } else {
                                  vErrors = null;
                                }
                              }
                            }
                            var valid0 = _errs41 === errors;
                          } else {
                            var valid0 = true;
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    } else {
      validate18.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate18.errors = vErrors;
  return errors === 0;
}
function validate17(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.type === undefined && (missing0 = "type")) ||
        (data.data === undefined && (missing0 = "data")) ||
        (data.timestamp === undefined && (missing0 = "timestamp"))
      ) {
        validate17.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.type !== undefined) {
          let data0 = data.type;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate17.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          if ("service_status" !== data0) {
            validate17.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "service_status" },
                message: "must be equal to constant",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.data !== undefined) {
            const _errs3 = errors;
            if (
              !validate18(data.data, {
                instancePath: instancePath + "/data",
                parentData: data,
                parentDataProperty: "data",
                rootData,
              })
            ) {
              vErrors = vErrors === null ? validate18.errors : vErrors.concat(validate18.errors);
              errors = vErrors.length;
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.timestamp !== undefined) {
              const _errs4 = errors;
              if (!(typeof data.timestamp == "number")) {
                validate17.errors = [
                  {
                    instancePath: instancePath + "/timestamp",
                    schemaPath: "#/properties/timestamp/type",
                    keyword: "type",
                    params: { type: "number" },
                    message: "must be number",
                  },
                ];
                return false;
              }
              var valid0 = _errs4 === errors;
            } else {
              var valid0 = true;
            }
          }
        }
      }
    } else {
      validate17.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate17.errors = vErrors;
  return errors === 0;
}
const schema26 = {
  properties: {
    type: { const: "execution_completed", title: "Type", type: "string" },
    data: { items: { $ref: "#/$defs/ExecutionCompletedData" }, title: "Data", type: "array" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "ExecutionCompletedWsMessage",
  type: "object",
};
const schema27 = {
  description:
    "Payload for execution_completed WebSocket messages.\n\n``kind`` discriminates handler invocations from job executions.\n``listener_id`` is set when ``kind='handler'``; ``job_id`` when ``kind='job'``.",
  properties: {
    kind: { enum: ["handler", "job"], title: "Kind", type: "string" },
    app_key: { title: "App Key", type: "string" },
    instance_index: { title: "Instance Index", type: "integer" },
    status: { $ref: "#/$defs/ExecutionStatus" },
    duration_ms: { title: "Duration Ms", type: "number" },
    error_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Error Type" },
    listener_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Listener Id" },
    job_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Job Id" },
    thread_leaked: { default: false, title: "Thread Leaked", type: "boolean" },
  },
  required: ["kind", "app_key", "instance_index", "status", "duration_ms"],
  title: "ExecutionCompletedData",
  type: "object",
};
const schema28 = {
  description:
    "Status values for handler invocations and job executions.\n\nCovers all values allowed by the ``executions.status`` CHECK constraint: migration 001\nintroduced the original four values (``success``, ``error``, ``cancelled``, ``timed_out``);\nmigration 009 added ``skipped``.\nPydantic v2 coerces plain strings to enum members on construction and\nserialises back to plain strings in JSON responses.",
  enum: ["success", "error", "cancelled", "timed_out", "skipped"],
  title: "ExecutionStatus",
  type: "string",
};
function validate21(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.kind === undefined && (missing0 = "kind")) ||
        (data.app_key === undefined && (missing0 = "app_key")) ||
        (data.instance_index === undefined && (missing0 = "instance_index")) ||
        (data.status === undefined && (missing0 = "status")) ||
        (data.duration_ms === undefined && (missing0 = "duration_ms"))
      ) {
        validate21.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.kind !== undefined) {
          let data0 = data.kind;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate21.errors = [
              {
                instancePath: instancePath + "/kind",
                schemaPath: "#/properties/kind/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          if (!(data0 === "handler" || data0 === "job")) {
            validate21.errors = [
              {
                instancePath: instancePath + "/kind",
                schemaPath: "#/properties/kind/enum",
                keyword: "enum",
                params: { allowedValues: schema27.properties.kind.enum },
                message: "must be equal to one of the allowed values",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.app_key !== undefined) {
            const _errs3 = errors;
            if (typeof data.app_key !== "string") {
              validate21.errors = [
                {
                  instancePath: instancePath + "/app_key",
                  schemaPath: "#/properties/app_key/type",
                  keyword: "type",
                  params: { type: "string" },
                  message: "must be string",
                },
              ];
              return false;
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.instance_index !== undefined) {
              let data2 = data.instance_index;
              const _errs5 = errors;
              if (!(typeof data2 == "number" && !(data2 % 1) && !isNaN(data2))) {
                validate21.errors = [
                  {
                    instancePath: instancePath + "/instance_index",
                    schemaPath: "#/properties/instance_index/type",
                    keyword: "type",
                    params: { type: "integer" },
                    message: "must be integer",
                  },
                ];
                return false;
              }
              var valid0 = _errs5 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.status !== undefined) {
                let data3 = data.status;
                const _errs7 = errors;
                if (typeof data3 !== "string") {
                  validate21.errors = [
                    {
                      instancePath: instancePath + "/status",
                      schemaPath: "#/$defs/ExecutionStatus/type",
                      keyword: "type",
                      params: { type: "string" },
                      message: "must be string",
                    },
                  ];
                  return false;
                }
                if (!(
                  data3 === "success" ||
                  data3 === "error" ||
                  data3 === "cancelled" ||
                  data3 === "timed_out" ||
                  data3 === "skipped"
                )) {
                  validate21.errors = [
                    {
                      instancePath: instancePath + "/status",
                      schemaPath: "#/$defs/ExecutionStatus/enum",
                      keyword: "enum",
                      params: { allowedValues: schema28.enum },
                      message: "must be equal to one of the allowed values",
                    },
                  ];
                  return false;
                }
                var valid0 = _errs7 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.duration_ms !== undefined) {
                  const _errs10 = errors;
                  if (!(typeof data.duration_ms == "number")) {
                    validate21.errors = [
                      {
                        instancePath: instancePath + "/duration_ms",
                        schemaPath: "#/properties/duration_ms/type",
                        keyword: "type",
                        params: { type: "number" },
                        message: "must be number",
                      },
                    ];
                    return false;
                  }
                  var valid0 = _errs10 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.error_type !== undefined) {
                    let data5 = data.error_type;
                    const _errs12 = errors;
                    const _errs13 = errors;
                    let valid2 = false;
                    const _errs14 = errors;
                    if (typeof data5 !== "string") {
                      const err0 = {
                        instancePath: instancePath + "/error_type",
                        schemaPath: "#/properties/error_type/anyOf/0/type",
                        keyword: "type",
                        params: { type: "string" },
                        message: "must be string",
                      };
                      if (vErrors === null) {
                        vErrors = [err0];
                      } else {
                        vErrors.push(err0);
                      }
                      errors++;
                    }
                    var _valid0 = _errs14 === errors;
                    valid2 = valid2 || _valid0;
                    if (!valid2) {
                      const _errs16 = errors;
                      if (data5 !== null) {
                        const err1 = {
                          instancePath: instancePath + "/error_type",
                          schemaPath: "#/properties/error_type/anyOf/1/type",
                          keyword: "type",
                          params: { type: "null" },
                          message: "must be null",
                        };
                        if (vErrors === null) {
                          vErrors = [err1];
                        } else {
                          vErrors.push(err1);
                        }
                        errors++;
                      }
                      var _valid0 = _errs16 === errors;
                      valid2 = valid2 || _valid0;
                    }
                    if (!valid2) {
                      const err2 = {
                        instancePath: instancePath + "/error_type",
                        schemaPath: "#/properties/error_type/anyOf",
                        keyword: "anyOf",
                        params: {},
                        message: "must match a schema in anyOf",
                      };
                      if (vErrors === null) {
                        vErrors = [err2];
                      } else {
                        vErrors.push(err2);
                      }
                      errors++;
                      validate21.errors = vErrors;
                      return false;
                    } else {
                      errors = _errs13;
                      if (vErrors !== null) {
                        if (_errs13) {
                          vErrors.length = _errs13;
                        } else {
                          vErrors = null;
                        }
                      }
                    }
                    var valid0 = _errs12 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.listener_id !== undefined) {
                      let data6 = data.listener_id;
                      const _errs18 = errors;
                      const _errs19 = errors;
                      let valid3 = false;
                      const _errs20 = errors;
                      if (!(typeof data6 == "number" && !(data6 % 1) && !isNaN(data6))) {
                        const err3 = {
                          instancePath: instancePath + "/listener_id",
                          schemaPath: "#/properties/listener_id/anyOf/0/type",
                          keyword: "type",
                          params: { type: "integer" },
                          message: "must be integer",
                        };
                        if (vErrors === null) {
                          vErrors = [err3];
                        } else {
                          vErrors.push(err3);
                        }
                        errors++;
                      }
                      var _valid1 = _errs20 === errors;
                      valid3 = valid3 || _valid1;
                      if (!valid3) {
                        const _errs22 = errors;
                        if (data6 !== null) {
                          const err4 = {
                            instancePath: instancePath + "/listener_id",
                            schemaPath: "#/properties/listener_id/anyOf/1/type",
                            keyword: "type",
                            params: { type: "null" },
                            message: "must be null",
                          };
                          if (vErrors === null) {
                            vErrors = [err4];
                          } else {
                            vErrors.push(err4);
                          }
                          errors++;
                        }
                        var _valid1 = _errs22 === errors;
                        valid3 = valid3 || _valid1;
                      }
                      if (!valid3) {
                        const err5 = {
                          instancePath: instancePath + "/listener_id",
                          schemaPath: "#/properties/listener_id/anyOf",
                          keyword: "anyOf",
                          params: {},
                          message: "must match a schema in anyOf",
                        };
                        if (vErrors === null) {
                          vErrors = [err5];
                        } else {
                          vErrors.push(err5);
                        }
                        errors++;
                        validate21.errors = vErrors;
                        return false;
                      } else {
                        errors = _errs19;
                        if (vErrors !== null) {
                          if (_errs19) {
                            vErrors.length = _errs19;
                          } else {
                            vErrors = null;
                          }
                        }
                      }
                      var valid0 = _errs18 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.job_id !== undefined) {
                        let data7 = data.job_id;
                        const _errs24 = errors;
                        const _errs25 = errors;
                        let valid4 = false;
                        const _errs26 = errors;
                        if (!(typeof data7 == "number" && !(data7 % 1) && !isNaN(data7))) {
                          const err6 = {
                            instancePath: instancePath + "/job_id",
                            schemaPath: "#/properties/job_id/anyOf/0/type",
                            keyword: "type",
                            params: { type: "integer" },
                            message: "must be integer",
                          };
                          if (vErrors === null) {
                            vErrors = [err6];
                          } else {
                            vErrors.push(err6);
                          }
                          errors++;
                        }
                        var _valid2 = _errs26 === errors;
                        valid4 = valid4 || _valid2;
                        if (!valid4) {
                          const _errs28 = errors;
                          if (data7 !== null) {
                            const err7 = {
                              instancePath: instancePath + "/job_id",
                              schemaPath: "#/properties/job_id/anyOf/1/type",
                              keyword: "type",
                              params: { type: "null" },
                              message: "must be null",
                            };
                            if (vErrors === null) {
                              vErrors = [err7];
                            } else {
                              vErrors.push(err7);
                            }
                            errors++;
                          }
                          var _valid2 = _errs28 === errors;
                          valid4 = valid4 || _valid2;
                        }
                        if (!valid4) {
                          const err8 = {
                            instancePath: instancePath + "/job_id",
                            schemaPath: "#/properties/job_id/anyOf",
                            keyword: "anyOf",
                            params: {},
                            message: "must match a schema in anyOf",
                          };
                          if (vErrors === null) {
                            vErrors = [err8];
                          } else {
                            vErrors.push(err8);
                          }
                          errors++;
                          validate21.errors = vErrors;
                          return false;
                        } else {
                          errors = _errs25;
                          if (vErrors !== null) {
                            if (_errs25) {
                              vErrors.length = _errs25;
                            } else {
                              vErrors = null;
                            }
                          }
                        }
                        var valid0 = _errs24 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.thread_leaked !== undefined) {
                          const _errs30 = errors;
                          if (typeof data.thread_leaked !== "boolean") {
                            validate21.errors = [
                              {
                                instancePath: instancePath + "/thread_leaked",
                                schemaPath: "#/properties/thread_leaked/type",
                                keyword: "type",
                                params: { type: "boolean" },
                                message: "must be boolean",
                              },
                            ];
                            return false;
                          }
                          var valid0 = _errs30 === errors;
                        } else {
                          var valid0 = true;
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    } else {
      validate21.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate21.errors = vErrors;
  return errors === 0;
}
function validate20(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.type === undefined && (missing0 = "type")) ||
        (data.data === undefined && (missing0 = "data")) ||
        (data.timestamp === undefined && (missing0 = "timestamp"))
      ) {
        validate20.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.type !== undefined) {
          let data0 = data.type;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate20.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          if ("execution_completed" !== data0) {
            validate20.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "execution_completed" },
                message: "must be equal to constant",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.data !== undefined) {
            let data1 = data.data;
            const _errs3 = errors;
            if (errors === _errs3) {
              if (Array.isArray(data1)) {
                var valid1 = true;
                const len0 = data1.length;
                for (let i0 = 0; i0 < len0; i0++) {
                  const _errs5 = errors;
                  if (
                    !validate21(data1[i0], {
                      instancePath: instancePath + "/data/" + i0,
                      parentData: data1,
                      parentDataProperty: i0,
                      rootData,
                    })
                  ) {
                    vErrors = vErrors === null ? validate21.errors : vErrors.concat(validate21.errors);
                    errors = vErrors.length;
                  }
                  var valid1 = _errs5 === errors;
                  if (!valid1) {
                    break;
                  }
                }
              } else {
                validate20.errors = [
                  {
                    instancePath: instancePath + "/data",
                    schemaPath: "#/properties/data/type",
                    keyword: "type",
                    params: { type: "array" },
                    message: "must be array",
                  },
                ];
                return false;
              }
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.timestamp !== undefined) {
              const _errs6 = errors;
              if (!(typeof data.timestamp == "number")) {
                validate20.errors = [
                  {
                    instancePath: instancePath + "/timestamp",
                    schemaPath: "#/properties/timestamp/type",
                    keyword: "type",
                    params: { type: "number" },
                    message: "must be number",
                  },
                ];
                return false;
              }
              var valid0 = _errs6 === errors;
            } else {
              var valid0 = true;
            }
          }
        }
      }
    } else {
      validate20.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate20.errors = vErrors;
  return errors === 0;
}
const schema29 = {
  properties: {
    type: { const: "app_manifests_changed", title: "Type", type: "string" },
    data: { $ref: "#/$defs/AppManifestsChangedData" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "AppManifestsChangedWsMessage",
  type: "object",
};
const schema30 = {
  description:
    'Payload for a completed app load/reload pass broadcast over WebSocket.\n\nCarries no fields — it is a refetch signal, not a diff. The event that triggers it\n(``HASSETTE_EVENT_APP_LOAD_COMPLETED``) fires after a full bootstrap or reload pass over\nall apps and does not identify which app(s) changed, so clients should treat receipt as\n"manifest status may be stale, refetch" rather than inspect the payload for detail.',
  properties: {},
  title: "AppManifestsChangedData",
  type: "object",
};
function validate23(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.type === undefined && (missing0 = "type")) ||
        (data.data === undefined && (missing0 = "data")) ||
        (data.timestamp === undefined && (missing0 = "timestamp"))
      ) {
        validate23.errors = [
          {
            instancePath,
            schemaPath: "#/required",
            keyword: "required",
            params: { missingProperty: missing0 },
            message: "must have required property '" + missing0 + "'",
          },
        ];
        return false;
      } else {
        if (data.type !== undefined) {
          let data0 = data.type;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate23.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/type",
                keyword: "type",
                params: { type: "string" },
                message: "must be string",
              },
            ];
            return false;
          }
          if ("app_manifests_changed" !== data0) {
            validate23.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "app_manifests_changed" },
                message: "must be equal to constant",
              },
            ];
            return false;
          }
          var valid0 = _errs1 === errors;
        } else {
          var valid0 = true;
        }
        if (valid0) {
          if (data.data !== undefined) {
            let data1 = data.data;
            const _errs3 = errors;
            const _errs4 = errors;
            if (errors === _errs4) {
              if (!(data1 && typeof data1 == "object" && !Array.isArray(data1))) {
                validate23.errors = [
                  {
                    instancePath: instancePath + "/data",
                    schemaPath: "#/$defs/AppManifestsChangedData/type",
                    keyword: "type",
                    params: { type: "object" },
                    message: "must be object",
                  },
                ];
                return false;
              }
            }
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.timestamp !== undefined) {
              const _errs6 = errors;
              if (!(typeof data.timestamp == "number")) {
                validate23.errors = [
                  {
                    instancePath: instancePath + "/timestamp",
                    schemaPath: "#/properties/timestamp/type",
                    keyword: "type",
                    params: { type: "number" },
                    message: "must be number",
                  },
                ];
                return false;
              }
              var valid0 = _errs6 === errors;
            } else {
              var valid0 = true;
            }
          }
        }
      }
    } else {
      validate23.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate23.errors = vErrors;
  return errors === 0;
}
function validate10(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      const tag0 = data.type;
      if (typeof tag0 == "string") {
        if (tag0 === "app_status_changed") {
          if (!validate11(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate11.errors : vErrors.concat(validate11.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "log") {
          if (!validate14(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate14.errors : vErrors.concat(validate14.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "connected") {
          if (!validate15(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate15.errors : vErrors.concat(validate15.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "connectivity") {
          if (!validate16(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate16.errors : vErrors.concat(validate16.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "service_status") {
          if (!validate17(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate17.errors : vErrors.concat(validate17.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "execution_completed") {
          if (!validate20(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate20.errors : vErrors.concat(validate20.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "app_manifests_changed") {
          if (!validate23(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate23.errors : vErrors.concat(validate23.errors);
            errors = vErrors.length;
          }
        } else {
          validate10.errors = [
            {
              instancePath,
              schemaPath: "#/discriminator",
              keyword: "discriminator",
              params: { error: "mapping", tag: "type", tagValue: tag0 },
              message: 'value of tag "type" must be in oneOf',
            },
          ];
          return false;
        }
      } else {
        validate10.errors = [
          {
            instancePath,
            schemaPath: "#/discriminator",
            keyword: "discriminator",
            params: { error: "tag", tag: "type", tagValue: tag0 },
            message: 'tag "type" must be string',
          },
        ];
        return false;
      }
    }
  }
  validate10.errors = vErrors;
  return errors === 0;
}
