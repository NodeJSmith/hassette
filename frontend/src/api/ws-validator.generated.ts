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
    AppStatus: {
      description:
        "An app's overall lifecycle status across its instances (distinct from the per-instance ``ResourceStatus``).\n\nMembers are listed in rollup order: the first that applies is the app's status. Only tracked instances count;\na configured instance that isn't tracked (shown as ``stopped``) never does.",
      enum: ["disabled", "blocked", "degraded", "failed", "starting", "stopping", "running", "stopped"],
      title: "AppStatus",
      type: "string",
    },
    AppStatusChangedData: {
      description:
        "An app instance changed lifecycle status.\n\nApply it only when ``status_revision`` is strictly greater than the ``AppSummary.status_revision`` of the row it\nupdates; on a tie the summary wins. The ``exception*`` fields describe the error that caused the change, and\nare ``None`` when no error did.",
      properties: {
        app_key: { title: "App Key", type: "string" },
        instance_name: { title: "Instance Name", type: "string" },
        status: { $ref: "#/$defs/ResourceStatus" },
        status_revision: {
          description:
            "The app-status revision this change was written at; comparable with ``AppSummary.status_revision``.",
          title: "Status Revision",
          type: "integer",
        },
        boot_id: {
          description:
            "Identifies the hassette boot that sent the message; a new value means the server restarted. Ordering doesn't\nneed it, since ``status_revision`` keeps increasing across restarts; it lets a client reset state it keeps per\nserver process.",
          title: "Boot Id",
          type: "string",
        },
        app_status: {
          $ref: "#/$defs/AppStatus",
          description:
            "The app's rollup status after this change, equal to the ``AppSummary.status`` read at ``status_revision``.",
        },
        previous_status: { anyOf: [{ $ref: "#/$defs/ResourceStatus" }, { type: "null" }], default: null },
        class_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Class Name" },
        exception: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception" },
        exception_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Type" },
        exception_traceback: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          title: "Exception Traceback",
        },
        needs_restart: {
          anyOf: [{ $ref: "#/$defs/NeedsRestart" }, { type: "null" }],
          default: null,
          description:
            "Set when this change flagged the instance needs-restart (only a ``failed`` change can), so a client can show\nit with the status.",
        },
      },
      required: ["app_key", "instance_name", "status", "status_revision", "boot_id", "app_status"],
      title: "AppStatusChangedData",
      type: "object",
    },
    AppStatusChangedWsMessage: {
      description: "Envelope for ``AppStatusChangedData``.",
      properties: {
        type: { const: "app_status_changed", title: "Type", type: "string" },
        data: { $ref: "#/$defs/AppStatusChangedData" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "AppStatusChangedWsMessage",
      type: "object",
    },
    AppsChangedData: {
      description:
        'Payload for an app-list refresh broadcast over WebSocket.\n\nCarries no fields and does not identify which apps changed — it is a refetch\nsignal, not a diff. Clients should treat receipt as "app status may be\nstale, refetch" rather than inspect the payload.',
      properties: {},
      title: "AppsChangedData",
      type: "object",
    },
    AppsChangedWsMessage: {
      description: "Envelope for ``AppsChangedData``.",
      properties: {
        type: { const: "apps_changed", title: "Type", type: "string" },
        data: { $ref: "#/$defs/AppsChangedData" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "AppsChangedWsMessage",
      type: "object",
    },
    ConnectedData: {
      description:
        "Server state sent once, as the first message after a WebSocket connection opens.\n\n``version`` is the server's hassette version; a client can compare it with its own to detect an upgrade.",
      properties: {
        uptime_seconds: { title: "Uptime Seconds", type: "number" },
        entity_count: { title: "Entity Count", type: "integer" },
        app_count: {
          description:
            "Number of app instances currently tracked (starting, running, or failed), not the number of configured apps.\n\nSame meaning as ``SystemStatusResponse.app_count``.",
          title: "App Count",
          type: "integer",
        },
        version: { default: "", title: "Version", type: "string" },
      },
      required: ["uptime_seconds", "entity_count", "app_count"],
      title: "ConnectedData",
      type: "object",
    },
    ConnectedWsMessage: {
      description: "Envelope for ``ConnectedData``.",
      properties: {
        type: { const: "connected", title: "Type", type: "string" },
        data: { $ref: "#/$defs/ConnectedData" },
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
      description: "Envelope for ``ConnectivityData``.",
      properties: {
        type: { const: "connectivity", title: "Type", type: "string" },
        data: { $ref: "#/$defs/ConnectivityData" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "ConnectivityWsMessage",
      type: "object",
    },
    DeclaredEntity: {
      description:
        "A Home Assistant button, switch or sensor an app instance declares through ``self.integration``.\n\nNested in ``AppInstance.entities`` on ``GET /api/apps``. Every platform shares one flat shape so a client\nthat meets a platform it doesn't know can skip that entity and keep the rest: ``unit``, ``device_class``,\n``state_class`` and ``options`` are set for a sensor only.",
      properties: {
        key: {
          description: "The entity's key: lowercase letters, digits and ``_``, unique within its instance.",
          title: "Key",
          type: "string",
        },
        platform: {
          description: "``button``, ``switch`` or ``sensor``.",
          enum: ["button", "switch", "sensor"],
          title: "Platform",
          type: "string",
        },
        name: { description: "The entity's display name.", title: "Name", type: "string" },
        default_entity_id: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          description:
            "The entity id the app suggests, applied only when the entity is first created in Home Assistant.",
          title: "Default Entity Id",
        },
        entity_category: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          description:
            "``config`` or ``diagnostic``: where Home Assistant files the entity on its device page. ``None`` for a\nprimary entity.",
          title: "Entity Category",
        },
        icon: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          description:
            "The entity's icon, such as ``mdi:cat``. ``None`` for Home Assistant's default icon. An icon set by hand in\nHome Assistant's entity registry takes precedence.",
          title: "Icon",
        },
        unit: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          description: "A sensor's unit of measurement.",
          title: "Unit",
        },
        device_class: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          description: "A sensor's Home Assistant device class.",
          title: "Device Class",
        },
        state_class: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          description: "A sensor's Home Assistant state class.",
          title: "State Class",
        },
        options: {
          anyOf: [{ items: { type: "string" }, type: "array" }, { type: "null" }],
          default: null,
          description: "An enum sensor's allowed values.",
          title: "Options",
        },
        value: {
          anyOf: [{ type: "integer" }, { type: "number" }, { type: "string" }, { type: "boolean" }, { type: "null" }],
          default: null,
          description:
            "A switch's on/off state or a sensor's value; ``None`` for a button and for a sensor that is unknown. A\ntimestamp sensor's value is an ISO 8601 string with offset, a date sensor's an ISO 8601 date.",
          title: "Value",
        },
        attributes: {
          additionalProperties: true,
          description: "The state attributes the app last set with the value.",
          title: "Attributes",
          type: "object",
        },
      },
      required: ["key", "platform", "name"],
      title: "DeclaredEntity",
      type: "object",
    },
    EntityStateChangedData: {
      description:
        "One app-declared entity's committed state changed.\n\n``boot_id`` and ``entity_revision`` are the same counters ``GET /api/apps`` reports. Apply this message only\nwhen its ``entity_revision`` is newer than the last one applied for the same ``boot_id``; revisions skip values,\nand a lost message is repaired only by the next listing fetch. Declaration commits send no message: entities\nappear and disappear only through the listing.",
      properties: {
        boot_id: {
          description: "Identifies the hassette boot that sent the message; a new value means the server restarted.",
          title: "Boot Id",
          type: "string",
        },
        entity_revision: {
          description: "The hassette-wide entity revision this change was committed at.",
          title: "Entity Revision",
          type: "integer",
        },
        app_key: { title: "App Key", type: "string" },
        instance_name: { title: "Instance Name", type: "string" },
        entity: {
          $ref: "#/$defs/DeclaredEntity",
          description: "The entity's full description and new state, as the listing reports it.",
        },
      },
      required: ["boot_id", "entity_revision", "app_key", "instance_name", "entity"],
      title: "EntityStateChangedData",
      type: "object",
    },
    EntityStateChangedWsMessage: {
      description: "Envelope for ``EntityStateChangedData``.",
      properties: {
        type: { const: "entity_state_changed", title: "Type", type: "string" },
        data: { $ref: "#/$defs/EntityStateChangedData" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "EntityStateChangedWsMessage",
      type: "object",
    },
    ExecutionCompletedData: {
      description:
        "Payload for execution_completed WebSocket messages.\n\n``kind`` discriminates handler invocations from job executions.\n``listener_id`` is set when ``kind='handler'``; ``job_id`` when ``kind='job'``.",
      properties: {
        kind: { enum: ["handler", "job"], title: "Kind", type: "string" },
        app_key: { title: "App Key", type: "string" },
        status: { $ref: "#/$defs/ExecutionStatus" },
        duration_ms: { title: "Duration Ms", type: "number" },
        error_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Error Type" },
        listener_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Listener Id" },
        job_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Job Id" },
        thread_leaked: { default: false, title: "Thread Leaked", type: "boolean" },
      },
      required: ["kind", "app_key", "status", "duration_ms"],
      title: "ExecutionCompletedData",
      type: "object",
    },
    ExecutionCompletedWsMessage: {
      description: "Envelope for a batch of ``ExecutionCompletedData``.",
      properties: {
        type: { const: "execution_completed", title: "Type", type: "string" },
        data: {
          description: "App-tier executions persisted since the previous message, delivered together in one batch.",
          items: { $ref: "#/$defs/ExecutionCompletedData" },
          title: "Data",
          type: "array",
        },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "data", "timestamp"],
      title: "ExecutionCompletedWsMessage",
      type: "object",
    },
    ExecutionStatus: {
      description: "How a handler invocation or job execution ended.",
      enum: ["success", "error", "cancelled", "timed_out", "skipped"],
      title: "ExecutionStatus",
      type: "string",
    },
    LogHintWsMessage: {
      description:
        "New log records exist; refetch them over HTTP.\n\nCarries no records. Sent only to clients that subscribed to logs.",
      properties: {
        type: { const: "log_hint", title: "Type", type: "string" },
        timestamp: { title: "Timestamp", type: "number" },
      },
      required: ["type", "timestamp"],
      title: "LogHintWsMessage",
      type: "object",
    },
    NeedsRestart: {
      description:
        "Why an app instance needs a hassette restart: a teardown left work that may still be running.\n\nPython can't stop a coroutine that ignores cancellation, so the only recovery is restarting hassette. Until\nthen the instance reports ``failed``. Nested in ``AppInstance`` and in the ``app_status_changed`` WS event.",
      properties: {
        reason: {
          description:
            "What the teardown left behind, such as the tasks still pending or why its evidence is incomplete.",
          title: "Reason",
          type: "string",
        },
        pending_tasks: {
          description:
            "Names of the tasks still running when the teardown ended, including an initializer that hadn't stopped\n(``resource:initialize:<unique name>``). Can be empty when the evidence is incomplete (the instance was\nforce-terminated, or its shutdown raised); ``reason`` says which.",
          items: { type: "string" },
          title: "Pending Tasks",
          type: "array",
        },
        flagged_at: {
          description: "When the instance was flagged, in epoch seconds. The first flag stands until restart.",
          title: "Flagged At",
          type: "number",
        },
      },
      required: ["reason", "flagged_at"],
      title: "NeedsRestart",
      type: "object",
    },
    ResourceStatus: {
      description: "Enumeration for resource status.",
      enum: ["not_started", "starting", "running", "stopping", "stopped", "failed", "crashed"],
      title: "ResourceStatus",
      type: "string",
    },
    ServiceStatusData: {
      description:
        "A framework service changed lifecycle status.\n\nThe ``exception*`` fields describe the error that caused the change, and are ``None`` when no error did.",
      properties: {
        resource_name: { title: "Resource Name", type: "string" },
        status: { $ref: "#/$defs/ResourceStatus" },
        previous_status: { anyOf: [{ $ref: "#/$defs/ResourceStatus" }, { type: "null" }], default: null },
        exception: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception" },
        exception_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Type" },
        exception_traceback: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          title: "Exception Traceback",
        },
        ready: {
          default: false,
          description: "Whether the service had signalled readiness at the time of this status event.",
          title: "Ready",
          type: "boolean",
        },
        ready_phase: {
          anyOf: [{ type: "string" }, { type: "null" }],
          default: null,
          description: "Human-readable description of the current readiness phase, or None if not available.",
          title: "Ready Phase",
        },
      },
      required: ["resource_name", "status"],
      title: "ServiceStatusData",
      type: "object",
    },
    ServiceStatusWsMessage: {
      description: "Envelope for ``ServiceStatusData``.",
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
    { $ref: "#/$defs/LogHintWsMessage" },
    { $ref: "#/$defs/ConnectedWsMessage" },
    { $ref: "#/$defs/ConnectivityWsMessage" },
    { $ref: "#/$defs/ServiceStatusWsMessage" },
    { $ref: "#/$defs/ExecutionCompletedWsMessage" },
    { $ref: "#/$defs/AppsChangedWsMessage" },
    { $ref: "#/$defs/EntityStateChangedWsMessage" },
  ],
};
const schema34 = {
  description:
    "New log records exist; refetch them over HTTP.\n\nCarries no records. Sent only to clients that subscribed to logs.",
  properties: {
    type: { const: "log_hint", title: "Type", type: "string" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "timestamp"],
  title: "LogHintWsMessage",
  type: "object",
};
const schema12 = {
  description: "Envelope for ``AppStatusChangedData``.",
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
    "An app instance changed lifecycle status.\n\nApply it only when ``status_revision`` is strictly greater than the ``AppSummary.status_revision`` of the row it\nupdates; on a tie the summary wins. The ``exception*`` fields describe the error that caused the change, and\nare ``None`` when no error did.",
  properties: {
    app_key: { title: "App Key", type: "string" },
    instance_name: { title: "Instance Name", type: "string" },
    status: { $ref: "#/$defs/ResourceStatus" },
    status_revision: {
      description:
        "The app-status revision this change was written at; comparable with ``AppSummary.status_revision``.",
      title: "Status Revision",
      type: "integer",
    },
    boot_id: {
      description:
        "Identifies the hassette boot that sent the message; a new value means the server restarted. Ordering doesn't\nneed it, since ``status_revision`` keeps increasing across restarts; it lets a client reset state it keeps per\nserver process.",
      title: "Boot Id",
      type: "string",
    },
    app_status: {
      $ref: "#/$defs/AppStatus",
      description:
        "The app's rollup status after this change, equal to the ``AppSummary.status`` read at ``status_revision``.",
    },
    previous_status: { anyOf: [{ $ref: "#/$defs/ResourceStatus" }, { type: "null" }], default: null },
    class_name: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Class Name" },
    exception: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception" },
    exception_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Type" },
    exception_traceback: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Traceback" },
    needs_restart: {
      anyOf: [{ $ref: "#/$defs/NeedsRestart" }, { type: "null" }],
      default: null,
      description:
        "Set when this change flagged the instance needs-restart (only a ``failed`` change can), so a client can show\nit with the status.",
    },
  },
  required: ["app_key", "instance_name", "status", "status_revision", "boot_id", "app_status"],
  title: "AppStatusChangedData",
  type: "object",
};
const schema14 = {
  description: "Enumeration for resource status.",
  enum: ["not_started", "starting", "running", "stopping", "stopped", "failed", "crashed"],
  title: "ResourceStatus",
  type: "string",
};
const schema15 = {
  description:
    "An app's overall lifecycle status across its instances (distinct from the per-instance ``ResourceStatus``).\n\nMembers are listed in rollup order: the first that applies is the app's status. Only tracked instances count;\na configured instance that isn't tracked (shown as ``stopped``) never does.",
  enum: ["disabled", "blocked", "degraded", "failed", "starting", "stopping", "running", "stopped"],
  title: "AppStatus",
  type: "string",
};
const schema17 = {
  description:
    "Why an app instance needs a hassette restart: a teardown left work that may still be running.\n\nPython can't stop a coroutine that ignores cancellation, so the only recovery is restarting hassette. Until\nthen the instance reports ``failed``. Nested in ``AppInstance`` and in the ``app_status_changed`` WS event.",
  properties: {
    reason: {
      description: "What the teardown left behind, such as the tasks still pending or why its evidence is incomplete.",
      title: "Reason",
      type: "string",
    },
    pending_tasks: {
      description:
        "Names of the tasks still running when the teardown ended, including an initializer that hadn't stopped\n(``resource:initialize:<unique name>``). Can be empty when the evidence is incomplete (the instance was\nforce-terminated, or its shutdown raised); ``reason`` says which.",
      items: { type: "string" },
      title: "Pending Tasks",
      type: "array",
    },
    flagged_at: {
      description: "When the instance was flagged, in epoch seconds. The first flag stands until restart.",
      title: "Flagged At",
      type: "number",
    },
  },
  required: ["reason", "flagged_at"],
  title: "NeedsRestart",
  type: "object",
};
function validate12(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.app_key === undefined && (missing0 = "app_key")) ||
        (data.instance_name === undefined && (missing0 = "instance_name")) ||
        (data.status === undefined && (missing0 = "status")) ||
        (data.status_revision === undefined && (missing0 = "status_revision")) ||
        (data.boot_id === undefined && (missing0 = "boot_id")) ||
        (data.app_status === undefined && (missing0 = "app_status"))
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
          if (data.instance_name !== undefined) {
            const _errs3 = errors;
            if (typeof data.instance_name !== "string") {
              validate12.errors = [
                {
                  instancePath: instancePath + "/instance_name",
                  schemaPath: "#/properties/instance_name/type",
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
                data2 === "crashed"
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
              if (data.status_revision !== undefined) {
                let data3 = data.status_revision;
                const _errs8 = errors;
                if (!(typeof data3 == "number" && !(data3 % 1) && !isNaN(data3))) {
                  validate12.errors = [
                    {
                      instancePath: instancePath + "/status_revision",
                      schemaPath: "#/properties/status_revision/type",
                      keyword: "type",
                      params: { type: "integer" },
                      message: "must be integer",
                    },
                  ];
                  return false;
                }
                var valid0 = _errs8 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.boot_id !== undefined) {
                  const _errs10 = errors;
                  if (typeof data.boot_id !== "string") {
                    validate12.errors = [
                      {
                        instancePath: instancePath + "/boot_id",
                        schemaPath: "#/properties/boot_id/type",
                        keyword: "type",
                        params: { type: "string" },
                        message: "must be string",
                      },
                    ];
                    return false;
                  }
                  var valid0 = _errs10 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.app_status !== undefined) {
                    let data5 = data.app_status;
                    const _errs12 = errors;
                    if (typeof data5 !== "string") {
                      validate12.errors = [
                        {
                          instancePath: instancePath + "/app_status",
                          schemaPath: "#/$defs/AppStatus/type",
                          keyword: "type",
                          params: { type: "string" },
                          message: "must be string",
                        },
                      ];
                      return false;
                    }
                    if (!(
                      data5 === "disabled" ||
                      data5 === "blocked" ||
                      data5 === "degraded" ||
                      data5 === "failed" ||
                      data5 === "starting" ||
                      data5 === "stopping" ||
                      data5 === "running" ||
                      data5 === "stopped"
                    )) {
                      validate12.errors = [
                        {
                          instancePath: instancePath + "/app_status",
                          schemaPath: "#/$defs/AppStatus/enum",
                          keyword: "enum",
                          params: { allowedValues: schema15.enum },
                          message: "must be equal to one of the allowed values",
                        },
                      ];
                      return false;
                    }
                    var valid0 = _errs12 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.previous_status !== undefined) {
                      let data6 = data.previous_status;
                      const _errs15 = errors;
                      const _errs16 = errors;
                      let valid3 = false;
                      const _errs17 = errors;
                      if (typeof data6 !== "string") {
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
                        data6 === "not_started" ||
                        data6 === "starting" ||
                        data6 === "running" ||
                        data6 === "stopping" ||
                        data6 === "stopped" ||
                        data6 === "failed" ||
                        data6 === "crashed"
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
                      var _valid0 = _errs17 === errors;
                      valid3 = valid3 || _valid0;
                      if (!valid3) {
                        const _errs20 = errors;
                        if (data6 !== null) {
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
                        var _valid0 = _errs20 === errors;
                        valid3 = valid3 || _valid0;
                      }
                      if (!valid3) {
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
                        let data7 = data.class_name;
                        const _errs22 = errors;
                        const _errs23 = errors;
                        let valid5 = false;
                        const _errs24 = errors;
                        if (typeof data7 !== "string") {
                          const err4 = {
                            instancePath: instancePath + "/class_name",
                            schemaPath: "#/properties/class_name/anyOf/0/type",
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
                        var _valid1 = _errs24 === errors;
                        valid5 = valid5 || _valid1;
                        if (!valid5) {
                          const _errs26 = errors;
                          if (data7 !== null) {
                            const err5 = {
                              instancePath: instancePath + "/class_name",
                              schemaPath: "#/properties/class_name/anyOf/1/type",
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
                          var _valid1 = _errs26 === errors;
                          valid5 = valid5 || _valid1;
                        }
                        if (!valid5) {
                          const err6 = {
                            instancePath: instancePath + "/class_name",
                            schemaPath: "#/properties/class_name/anyOf",
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
                          errors = _errs23;
                          if (vErrors !== null) {
                            if (_errs23) {
                              vErrors.length = _errs23;
                            } else {
                              vErrors = null;
                            }
                          }
                        }
                        var valid0 = _errs22 === errors;
                      } else {
                        var valid0 = true;
                      }
                      if (valid0) {
                        if (data.exception !== undefined) {
                          let data8 = data.exception;
                          const _errs28 = errors;
                          const _errs29 = errors;
                          let valid6 = false;
                          const _errs30 = errors;
                          if (typeof data8 !== "string") {
                            const err7 = {
                              instancePath: instancePath + "/exception",
                              schemaPath: "#/properties/exception/anyOf/0/type",
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
                          var _valid2 = _errs30 === errors;
                          valid6 = valid6 || _valid2;
                          if (!valid6) {
                            const _errs32 = errors;
                            if (data8 !== null) {
                              const err8 = {
                                instancePath: instancePath + "/exception",
                                schemaPath: "#/properties/exception/anyOf/1/type",
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
                            var _valid2 = _errs32 === errors;
                            valid6 = valid6 || _valid2;
                          }
                          if (!valid6) {
                            const err9 = {
                              instancePath: instancePath + "/exception",
                              schemaPath: "#/properties/exception/anyOf",
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
                            errors = _errs29;
                            if (vErrors !== null) {
                              if (_errs29) {
                                vErrors.length = _errs29;
                              } else {
                                vErrors = null;
                              }
                            }
                          }
                          var valid0 = _errs28 === errors;
                        } else {
                          var valid0 = true;
                        }
                        if (valid0) {
                          if (data.exception_type !== undefined) {
                            let data9 = data.exception_type;
                            const _errs34 = errors;
                            const _errs35 = errors;
                            let valid7 = false;
                            const _errs36 = errors;
                            if (typeof data9 !== "string") {
                              const err10 = {
                                instancePath: instancePath + "/exception_type",
                                schemaPath: "#/properties/exception_type/anyOf/0/type",
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
                            var _valid3 = _errs36 === errors;
                            valid7 = valid7 || _valid3;
                            if (!valid7) {
                              const _errs38 = errors;
                              if (data9 !== null) {
                                const err11 = {
                                  instancePath: instancePath + "/exception_type",
                                  schemaPath: "#/properties/exception_type/anyOf/1/type",
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
                              var _valid3 = _errs38 === errors;
                              valid7 = valid7 || _valid3;
                            }
                            if (!valid7) {
                              const err12 = {
                                instancePath: instancePath + "/exception_type",
                                schemaPath: "#/properties/exception_type/anyOf",
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
                              errors = _errs35;
                              if (vErrors !== null) {
                                if (_errs35) {
                                  vErrors.length = _errs35;
                                } else {
                                  vErrors = null;
                                }
                              }
                            }
                            var valid0 = _errs34 === errors;
                          } else {
                            var valid0 = true;
                          }
                          if (valid0) {
                            if (data.exception_traceback !== undefined) {
                              let data10 = data.exception_traceback;
                              const _errs40 = errors;
                              const _errs41 = errors;
                              let valid8 = false;
                              const _errs42 = errors;
                              if (typeof data10 !== "string") {
                                const err13 = {
                                  instancePath: instancePath + "/exception_traceback",
                                  schemaPath: "#/properties/exception_traceback/anyOf/0/type",
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
                              var _valid4 = _errs42 === errors;
                              valid8 = valid8 || _valid4;
                              if (!valid8) {
                                const _errs44 = errors;
                                if (data10 !== null) {
                                  const err14 = {
                                    instancePath: instancePath + "/exception_traceback",
                                    schemaPath: "#/properties/exception_traceback/anyOf/1/type",
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
                                var _valid4 = _errs44 === errors;
                                valid8 = valid8 || _valid4;
                              }
                              if (!valid8) {
                                const err15 = {
                                  instancePath: instancePath + "/exception_traceback",
                                  schemaPath: "#/properties/exception_traceback/anyOf",
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
                                errors = _errs41;
                                if (vErrors !== null) {
                                  if (_errs41) {
                                    vErrors.length = _errs41;
                                  } else {
                                    vErrors = null;
                                  }
                                }
                              }
                              var valid0 = _errs40 === errors;
                            } else {
                              var valid0 = true;
                            }
                            if (valid0) {
                              if (data.needs_restart !== undefined) {
                                let data11 = data.needs_restart;
                                const _errs46 = errors;
                                const _errs47 = errors;
                                let valid9 = false;
                                const _errs48 = errors;
                                const _errs49 = errors;
                                if (errors === _errs49) {
                                  if (data11 && typeof data11 == "object" && !Array.isArray(data11)) {
                                    let missing1;
                                    if (
                                      (data11.reason === undefined && (missing1 = "reason")) ||
                                      (data11.flagged_at === undefined && (missing1 = "flagged_at"))
                                    ) {
                                      const err16 = {
                                        instancePath: instancePath + "/needs_restart",
                                        schemaPath: "#/$defs/NeedsRestart/required",
                                        keyword: "required",
                                        params: { missingProperty: missing1 },
                                        message: "must have required property '" + missing1 + "'",
                                      };
                                      if (vErrors === null) {
                                        vErrors = [err16];
                                      } else {
                                        vErrors.push(err16);
                                      }
                                      errors++;
                                    } else {
                                      if (data11.reason !== undefined) {
                                        const _errs51 = errors;
                                        if (typeof data11.reason !== "string") {
                                          const err17 = {
                                            instancePath: instancePath + "/needs_restart/reason",
                                            schemaPath: "#/$defs/NeedsRestart/properties/reason/type",
                                            keyword: "type",
                                            params: { type: "string" },
                                            message: "must be string",
                                          };
                                          if (vErrors === null) {
                                            vErrors = [err17];
                                          } else {
                                            vErrors.push(err17);
                                          }
                                          errors++;
                                        }
                                        var valid11 = _errs51 === errors;
                                      } else {
                                        var valid11 = true;
                                      }
                                      if (valid11) {
                                        if (data11.pending_tasks !== undefined) {
                                          let data13 = data11.pending_tasks;
                                          const _errs53 = errors;
                                          if (errors === _errs53) {
                                            if (Array.isArray(data13)) {
                                              var valid12 = true;
                                              const len0 = data13.length;
                                              for (let i0 = 0; i0 < len0; i0++) {
                                                const _errs55 = errors;
                                                if (typeof data13[i0] !== "string") {
                                                  const err18 = {
                                                    instancePath: instancePath + "/needs_restart/pending_tasks/" + i0,
                                                    schemaPath:
                                                      "#/$defs/NeedsRestart/properties/pending_tasks/items/type",
                                                    keyword: "type",
                                                    params: { type: "string" },
                                                    message: "must be string",
                                                  };
                                                  if (vErrors === null) {
                                                    vErrors = [err18];
                                                  } else {
                                                    vErrors.push(err18);
                                                  }
                                                  errors++;
                                                }
                                                var valid12 = _errs55 === errors;
                                                if (!valid12) {
                                                  break;
                                                }
                                              }
                                            } else {
                                              const err19 = {
                                                instancePath: instancePath + "/needs_restart/pending_tasks",
                                                schemaPath: "#/$defs/NeedsRestart/properties/pending_tasks/type",
                                                keyword: "type",
                                                params: { type: "array" },
                                                message: "must be array",
                                              };
                                              if (vErrors === null) {
                                                vErrors = [err19];
                                              } else {
                                                vErrors.push(err19);
                                              }
                                              errors++;
                                            }
                                          }
                                          var valid11 = _errs53 === errors;
                                        } else {
                                          var valid11 = true;
                                        }
                                        if (valid11) {
                                          if (data11.flagged_at !== undefined) {
                                            const _errs57 = errors;
                                            if (!(typeof data11.flagged_at == "number")) {
                                              const err20 = {
                                                instancePath: instancePath + "/needs_restart/flagged_at",
                                                schemaPath: "#/$defs/NeedsRestart/properties/flagged_at/type",
                                                keyword: "type",
                                                params: { type: "number" },
                                                message: "must be number",
                                              };
                                              if (vErrors === null) {
                                                vErrors = [err20];
                                              } else {
                                                vErrors.push(err20);
                                              }
                                              errors++;
                                            }
                                            var valid11 = _errs57 === errors;
                                          } else {
                                            var valid11 = true;
                                          }
                                        }
                                      }
                                    }
                                  } else {
                                    const err21 = {
                                      instancePath: instancePath + "/needs_restart",
                                      schemaPath: "#/$defs/NeedsRestart/type",
                                      keyword: "type",
                                      params: { type: "object" },
                                      message: "must be object",
                                    };
                                    if (vErrors === null) {
                                      vErrors = [err21];
                                    } else {
                                      vErrors.push(err21);
                                    }
                                    errors++;
                                  }
                                }
                                var _valid5 = _errs48 === errors;
                                valid9 = valid9 || _valid5;
                                if (!valid9) {
                                  const _errs59 = errors;
                                  if (data11 !== null) {
                                    const err22 = {
                                      instancePath: instancePath + "/needs_restart",
                                      schemaPath: "#/properties/needs_restart/anyOf/1/type",
                                      keyword: "type",
                                      params: { type: "null" },
                                      message: "must be null",
                                    };
                                    if (vErrors === null) {
                                      vErrors = [err22];
                                    } else {
                                      vErrors.push(err22);
                                    }
                                    errors++;
                                  }
                                  var _valid5 = _errs59 === errors;
                                  valid9 = valid9 || _valid5;
                                }
                                if (!valid9) {
                                  const err23 = {
                                    instancePath: instancePath + "/needs_restart",
                                    schemaPath: "#/properties/needs_restart/anyOf",
                                    keyword: "anyOf",
                                    params: {},
                                    message: "must match a schema in anyOf",
                                  };
                                  if (vErrors === null) {
                                    vErrors = [err23];
                                  } else {
                                    vErrors.push(err23);
                                  }
                                  errors++;
                                  validate12.errors = vErrors;
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
                                var valid0 = _errs46 === errors;
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
const schema18 = {
  description: "Envelope for ``ConnectedData``.",
  properties: {
    type: { const: "connected", title: "Type", type: "string" },
    data: { $ref: "#/$defs/ConnectedData" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "ConnectedWsMessage",
  type: "object",
};
const schema19 = {
  description:
    "Server state sent once, as the first message after a WebSocket connection opens.\n\n``version`` is the server's hassette version; a client can compare it with its own to detect an upgrade.",
  properties: {
    uptime_seconds: { title: "Uptime Seconds", type: "number" },
    entity_count: { title: "Entity Count", type: "integer" },
    app_count: {
      description:
        "Number of app instances currently tracked (starting, running, or failed), not the number of configured apps.\n\nSame meaning as ``SystemStatusResponse.app_count``.",
      title: "App Count",
      type: "integer",
    },
    version: { default: "", title: "Version", type: "string" },
  },
  required: ["uptime_seconds", "entity_count", "app_count"],
  title: "ConnectedData",
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
          if ("connected" !== data0) {
            validate14.errors = [
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
                  validate14.errors = [
                    {
                      instancePath: instancePath + "/data",
                      schemaPath: "#/$defs/ConnectedData/required",
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
                      validate14.errors = [
                        {
                          instancePath: instancePath + "/data/uptime_seconds",
                          schemaPath: "#/$defs/ConnectedData/properties/uptime_seconds/type",
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
                        validate14.errors = [
                          {
                            instancePath: instancePath + "/data/entity_count",
                            schemaPath: "#/$defs/ConnectedData/properties/entity_count/type",
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
                          validate14.errors = [
                            {
                              instancePath: instancePath + "/data/app_count",
                              schemaPath: "#/$defs/ConnectedData/properties/app_count/type",
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
                            validate14.errors = [
                              {
                                instancePath: instancePath + "/data/version",
                                schemaPath: "#/$defs/ConnectedData/properties/version/type",
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
                validate14.errors = [
                  {
                    instancePath: instancePath + "/data",
                    schemaPath: "#/$defs/ConnectedData/type",
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
              var valid0 = _errs14 === errors;
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
const schema20 = {
  description: "Envelope for ``ConnectivityData``.",
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
          if ("connectivity" !== data0) {
            validate15.errors = [
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
                  validate15.errors = [
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
                      validate15.errors = [
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
                validate15.errors = [
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
              var valid0 = _errs8 === errors;
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
const schema22 = {
  description: "Envelope for ``ServiceStatusData``.",
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
    "A framework service changed lifecycle status.\n\nThe ``exception*`` fields describe the error that caused the change, and are ``None`` when no error did.",
  properties: {
    resource_name: { title: "Resource Name", type: "string" },
    status: { $ref: "#/$defs/ResourceStatus" },
    previous_status: { anyOf: [{ $ref: "#/$defs/ResourceStatus" }, { type: "null" }], default: null },
    exception: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception" },
    exception_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Type" },
    exception_traceback: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Exception Traceback" },
    ready: {
      default: false,
      description: "Whether the service had signalled readiness at the time of this status event.",
      title: "Ready",
      type: "boolean",
    },
    ready_phase: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      description: "Human-readable description of the current readiness phase, or None if not available.",
      title: "Ready Phase",
    },
  },
  required: ["resource_name", "status"],
  title: "ServiceStatusData",
  type: "object",
};
function validate17(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.resource_name === undefined && (missing0 = "resource_name")) ||
        (data.status === undefined && (missing0 = "status"))
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
        if (data.resource_name !== undefined) {
          const _errs1 = errors;
          if (typeof data.resource_name !== "string") {
            validate17.errors = [
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
          if (data.status !== undefined) {
            let data1 = data.status;
            const _errs3 = errors;
            if (typeof data1 !== "string") {
              validate17.errors = [
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
              data1 === "not_started" ||
              data1 === "starting" ||
              data1 === "running" ||
              data1 === "stopping" ||
              data1 === "stopped" ||
              data1 === "failed" ||
              data1 === "crashed"
            )) {
              validate17.errors = [
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
            var valid0 = _errs3 === errors;
          } else {
            var valid0 = true;
          }
          if (valid0) {
            if (data.previous_status !== undefined) {
              let data2 = data.previous_status;
              const _errs6 = errors;
              const _errs7 = errors;
              let valid2 = false;
              const _errs8 = errors;
              if (typeof data2 !== "string") {
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
                data2 === "not_started" ||
                data2 === "starting" ||
                data2 === "running" ||
                data2 === "stopping" ||
                data2 === "stopped" ||
                data2 === "failed" ||
                data2 === "crashed"
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
              var _valid0 = _errs8 === errors;
              valid2 = valid2 || _valid0;
              if (!valid2) {
                const _errs11 = errors;
                if (data2 !== null) {
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
                var _valid0 = _errs11 === errors;
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
                validate17.errors = vErrors;
                return false;
              } else {
                errors = _errs7;
                if (vErrors !== null) {
                  if (_errs7) {
                    vErrors.length = _errs7;
                  } else {
                    vErrors = null;
                  }
                }
              }
              var valid0 = _errs6 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.exception !== undefined) {
                let data3 = data.exception;
                const _errs13 = errors;
                const _errs14 = errors;
                let valid4 = false;
                const _errs15 = errors;
                if (typeof data3 !== "string") {
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
                var _valid1 = _errs15 === errors;
                valid4 = valid4 || _valid1;
                if (!valid4) {
                  const _errs17 = errors;
                  if (data3 !== null) {
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
                  var _valid1 = _errs17 === errors;
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
                  validate17.errors = vErrors;
                  return false;
                } else {
                  errors = _errs14;
                  if (vErrors !== null) {
                    if (_errs14) {
                      vErrors.length = _errs14;
                    } else {
                      vErrors = null;
                    }
                  }
                }
                var valid0 = _errs13 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.exception_type !== undefined) {
                  let data4 = data.exception_type;
                  const _errs19 = errors;
                  const _errs20 = errors;
                  let valid5 = false;
                  const _errs21 = errors;
                  if (typeof data4 !== "string") {
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
                  var _valid2 = _errs21 === errors;
                  valid5 = valid5 || _valid2;
                  if (!valid5) {
                    const _errs23 = errors;
                    if (data4 !== null) {
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
                    var _valid2 = _errs23 === errors;
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
                    validate17.errors = vErrors;
                    return false;
                  } else {
                    errors = _errs20;
                    if (vErrors !== null) {
                      if (_errs20) {
                        vErrors.length = _errs20;
                      } else {
                        vErrors = null;
                      }
                    }
                  }
                  var valid0 = _errs19 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.exception_traceback !== undefined) {
                    let data5 = data.exception_traceback;
                    const _errs25 = errors;
                    const _errs26 = errors;
                    let valid6 = false;
                    const _errs27 = errors;
                    if (typeof data5 !== "string") {
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
                    var _valid3 = _errs27 === errors;
                    valid6 = valid6 || _valid3;
                    if (!valid6) {
                      const _errs29 = errors;
                      if (data5 !== null) {
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
                      var _valid3 = _errs29 === errors;
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
                      validate17.errors = vErrors;
                      return false;
                    } else {
                      errors = _errs26;
                      if (vErrors !== null) {
                        if (_errs26) {
                          vErrors.length = _errs26;
                        } else {
                          vErrors = null;
                        }
                      }
                    }
                    var valid0 = _errs25 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.ready !== undefined) {
                      const _errs31 = errors;
                      if (typeof data.ready !== "boolean") {
                        validate17.errors = [
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
                      var valid0 = _errs31 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.ready_phase !== undefined) {
                        let data7 = data.ready_phase;
                        const _errs33 = errors;
                        const _errs34 = errors;
                        let valid7 = false;
                        const _errs35 = errors;
                        if (typeof data7 !== "string") {
                          const err13 = {
                            instancePath: instancePath + "/ready_phase",
                            schemaPath: "#/properties/ready_phase/anyOf/0/type",
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
                              instancePath: instancePath + "/ready_phase",
                              schemaPath: "#/properties/ready_phase/anyOf/1/type",
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
                            instancePath: instancePath + "/ready_phase",
                            schemaPath: "#/properties/ready_phase/anyOf",
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
                          validate17.errors = vErrors;
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
                    }
                  }
                }
              }
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
          if ("service_status" !== data0) {
            validate16.errors = [
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
              !validate17(data.data, {
                instancePath: instancePath + "/data",
                parentData: data,
                parentDataProperty: "data",
                rootData,
              })
            ) {
              vErrors = vErrors === null ? validate17.errors : vErrors.concat(validate17.errors);
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
              var valid0 = _errs4 === errors;
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
const schema26 = {
  description: "Envelope for a batch of ``ExecutionCompletedData``.",
  properties: {
    type: { const: "execution_completed", title: "Type", type: "string" },
    data: {
      description: "App-tier executions persisted since the previous message, delivered together in one batch.",
      items: { $ref: "#/$defs/ExecutionCompletedData" },
      title: "Data",
      type: "array",
    },
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
    status: { $ref: "#/$defs/ExecutionStatus" },
    duration_ms: { title: "Duration Ms", type: "number" },
    error_type: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Error Type" },
    listener_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Listener Id" },
    job_id: { anyOf: [{ type: "integer" }, { type: "null" }], default: null, title: "Job Id" },
    thread_leaked: { default: false, title: "Thread Leaked", type: "boolean" },
  },
  required: ["kind", "app_key", "status", "duration_ms"],
  title: "ExecutionCompletedData",
  type: "object",
};
const schema28 = {
  description: "How a handler invocation or job execution ended.",
  enum: ["success", "error", "cancelled", "timed_out", "skipped"],
  title: "ExecutionStatus",
  type: "string",
};
function validate20(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.kind === undefined && (missing0 = "kind")) ||
        (data.app_key === undefined && (missing0 = "app_key")) ||
        (data.status === undefined && (missing0 = "status")) ||
        (data.duration_ms === undefined && (missing0 = "duration_ms"))
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
        if (data.kind !== undefined) {
          let data0 = data.kind;
          const _errs1 = errors;
          if (typeof data0 !== "string") {
            validate20.errors = [
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
            validate20.errors = [
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
              validate20.errors = [
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
            if (data.status !== undefined) {
              let data2 = data.status;
              const _errs5 = errors;
              if (typeof data2 !== "string") {
                validate20.errors = [
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
                data2 === "success" ||
                data2 === "error" ||
                data2 === "cancelled" ||
                data2 === "timed_out" ||
                data2 === "skipped"
              )) {
                validate20.errors = [
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
              var valid0 = _errs5 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.duration_ms !== undefined) {
                const _errs8 = errors;
                if (!(typeof data.duration_ms == "number")) {
                  validate20.errors = [
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
                var valid0 = _errs8 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.error_type !== undefined) {
                  let data4 = data.error_type;
                  const _errs10 = errors;
                  const _errs11 = errors;
                  let valid2 = false;
                  const _errs12 = errors;
                  if (typeof data4 !== "string") {
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
                  var _valid0 = _errs12 === errors;
                  valid2 = valid2 || _valid0;
                  if (!valid2) {
                    const _errs14 = errors;
                    if (data4 !== null) {
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
                    var _valid0 = _errs14 === errors;
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
                    validate20.errors = vErrors;
                    return false;
                  } else {
                    errors = _errs11;
                    if (vErrors !== null) {
                      if (_errs11) {
                        vErrors.length = _errs11;
                      } else {
                        vErrors = null;
                      }
                    }
                  }
                  var valid0 = _errs10 === errors;
                } else {
                  var valid0 = true;
                }
                if (valid0) {
                  if (data.listener_id !== undefined) {
                    let data5 = data.listener_id;
                    const _errs16 = errors;
                    const _errs17 = errors;
                    let valid3 = false;
                    const _errs18 = errors;
                    if (!(typeof data5 == "number" && !(data5 % 1) && !isNaN(data5))) {
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
                    var _valid1 = _errs18 === errors;
                    valid3 = valid3 || _valid1;
                    if (!valid3) {
                      const _errs20 = errors;
                      if (data5 !== null) {
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
                      var _valid1 = _errs20 === errors;
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
                      validate20.errors = vErrors;
                      return false;
                    } else {
                      errors = _errs17;
                      if (vErrors !== null) {
                        if (_errs17) {
                          vErrors.length = _errs17;
                        } else {
                          vErrors = null;
                        }
                      }
                    }
                    var valid0 = _errs16 === errors;
                  } else {
                    var valid0 = true;
                  }
                  if (valid0) {
                    if (data.job_id !== undefined) {
                      let data6 = data.job_id;
                      const _errs22 = errors;
                      const _errs23 = errors;
                      let valid4 = false;
                      const _errs24 = errors;
                      if (!(typeof data6 == "number" && !(data6 % 1) && !isNaN(data6))) {
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
                      var _valid2 = _errs24 === errors;
                      valid4 = valid4 || _valid2;
                      if (!valid4) {
                        const _errs26 = errors;
                        if (data6 !== null) {
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
                        var _valid2 = _errs26 === errors;
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
                        validate20.errors = vErrors;
                        return false;
                      } else {
                        errors = _errs23;
                        if (vErrors !== null) {
                          if (_errs23) {
                            vErrors.length = _errs23;
                          } else {
                            vErrors = null;
                          }
                        }
                      }
                      var valid0 = _errs22 === errors;
                    } else {
                      var valid0 = true;
                    }
                    if (valid0) {
                      if (data.thread_leaked !== undefined) {
                        const _errs28 = errors;
                        if (typeof data.thread_leaked !== "boolean") {
                          validate20.errors = [
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
                        var valid0 = _errs28 === errors;
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
function validate19(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
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
        validate19.errors = [
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
            validate19.errors = [
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
            validate19.errors = [
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
                    !validate20(data1[i0], {
                      instancePath: instancePath + "/data/" + i0,
                      parentData: data1,
                      parentDataProperty: i0,
                      rootData,
                    })
                  ) {
                    vErrors = vErrors === null ? validate20.errors : vErrors.concat(validate20.errors);
                    errors = vErrors.length;
                  }
                  var valid1 = _errs5 === errors;
                  if (!valid1) {
                    break;
                  }
                }
              } else {
                validate19.errors = [
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
                validate19.errors = [
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
      validate19.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate19.errors = vErrors;
  return errors === 0;
}
const schema29 = {
  description: "Envelope for ``AppsChangedData``.",
  properties: {
    type: { const: "apps_changed", title: "Type", type: "string" },
    data: { $ref: "#/$defs/AppsChangedData" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "AppsChangedWsMessage",
  type: "object",
};
const schema30 = {
  description:
    'Payload for an app-list refresh broadcast over WebSocket.\n\nCarries no fields and does not identify which apps changed — it is a refetch\nsignal, not a diff. Clients should treat receipt as "app status may be\nstale, refetch" rather than inspect the payload.',
  properties: {},
  title: "AppsChangedData",
  type: "object",
};
function validate22(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
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
        validate22.errors = [
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
            validate22.errors = [
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
          if ("apps_changed" !== data0) {
            validate22.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "apps_changed" },
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
                validate22.errors = [
                  {
                    instancePath: instancePath + "/data",
                    schemaPath: "#/$defs/AppsChangedData/type",
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
                validate22.errors = [
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
      validate22.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate22.errors = vErrors;
  return errors === 0;
}
const schema31 = {
  description: "Envelope for ``EntityStateChangedData``.",
  properties: {
    type: { const: "entity_state_changed", title: "Type", type: "string" },
    data: { $ref: "#/$defs/EntityStateChangedData" },
    timestamp: { title: "Timestamp", type: "number" },
  },
  required: ["type", "data", "timestamp"],
  title: "EntityStateChangedWsMessage",
  type: "object",
};
const schema32 = {
  description:
    "One app-declared entity's committed state changed.\n\n``boot_id`` and ``entity_revision`` are the same counters ``GET /api/apps`` reports. Apply this message only\nwhen its ``entity_revision`` is newer than the last one applied for the same ``boot_id``; revisions skip values,\nand a lost message is repaired only by the next listing fetch. Declaration commits send no message: entities\nappear and disappear only through the listing.",
  properties: {
    boot_id: {
      description: "Identifies the hassette boot that sent the message; a new value means the server restarted.",
      title: "Boot Id",
      type: "string",
    },
    entity_revision: {
      description: "The hassette-wide entity revision this change was committed at.",
      title: "Entity Revision",
      type: "integer",
    },
    app_key: { title: "App Key", type: "string" },
    instance_name: { title: "Instance Name", type: "string" },
    entity: {
      $ref: "#/$defs/DeclaredEntity",
      description: "The entity's full description and new state, as the listing reports it.",
    },
  },
  required: ["boot_id", "entity_revision", "app_key", "instance_name", "entity"],
  title: "EntityStateChangedData",
  type: "object",
};
const schema33 = {
  description:
    "A Home Assistant button, switch or sensor an app instance declares through ``self.integration``.\n\nNested in ``AppInstance.entities`` on ``GET /api/apps``. Every platform shares one flat shape so a client\nthat meets a platform it doesn't know can skip that entity and keep the rest: ``unit``, ``device_class``,\n``state_class`` and ``options`` are set for a sensor only.",
  properties: {
    key: {
      description: "The entity's key: lowercase letters, digits and ``_``, unique within its instance.",
      title: "Key",
      type: "string",
    },
    platform: {
      description: "``button``, ``switch`` or ``sensor``.",
      enum: ["button", "switch", "sensor"],
      title: "Platform",
      type: "string",
    },
    name: { description: "The entity's display name.", title: "Name", type: "string" },
    default_entity_id: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      description: "The entity id the app suggests, applied only when the entity is first created in Home Assistant.",
      title: "Default Entity Id",
    },
    entity_category: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      description:
        "``config`` or ``diagnostic``: where Home Assistant files the entity on its device page. ``None`` for a\nprimary entity.",
      title: "Entity Category",
    },
    icon: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      description:
        "The entity's icon, such as ``mdi:cat``. ``None`` for Home Assistant's default icon. An icon set by hand in\nHome Assistant's entity registry takes precedence.",
      title: "Icon",
    },
    unit: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      description: "A sensor's unit of measurement.",
      title: "Unit",
    },
    device_class: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      description: "A sensor's Home Assistant device class.",
      title: "Device Class",
    },
    state_class: {
      anyOf: [{ type: "string" }, { type: "null" }],
      default: null,
      description: "A sensor's Home Assistant state class.",
      title: "State Class",
    },
    options: {
      anyOf: [{ items: { type: "string" }, type: "array" }, { type: "null" }],
      default: null,
      description: "An enum sensor's allowed values.",
      title: "Options",
    },
    value: {
      anyOf: [{ type: "integer" }, { type: "number" }, { type: "string" }, { type: "boolean" }, { type: "null" }],
      default: null,
      description:
        "A switch's on/off state or a sensor's value; ``None`` for a button and for a sensor that is unknown. A\ntimestamp sensor's value is an ISO 8601 string with offset, a date sensor's an ISO 8601 date.",
      title: "Value",
    },
    attributes: {
      additionalProperties: true,
      description: "The state attributes the app last set with the value.",
      title: "Attributes",
      type: "object",
    },
  },
  required: ["key", "platform", "name"],
  title: "DeclaredEntity",
  type: "object",
};
function validate24(data, { instancePath = "", parentData, parentDataProperty, rootData = data } = {}) {
  let vErrors = null;
  let errors = 0;
  if (errors === 0) {
    if (data && typeof data == "object" && !Array.isArray(data)) {
      let missing0;
      if (
        (data.boot_id === undefined && (missing0 = "boot_id")) ||
        (data.entity_revision === undefined && (missing0 = "entity_revision")) ||
        (data.app_key === undefined && (missing0 = "app_key")) ||
        (data.instance_name === undefined && (missing0 = "instance_name")) ||
        (data.entity === undefined && (missing0 = "entity"))
      ) {
        validate24.errors = [
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
        if (data.boot_id !== undefined) {
          const _errs1 = errors;
          if (typeof data.boot_id !== "string") {
            validate24.errors = [
              {
                instancePath: instancePath + "/boot_id",
                schemaPath: "#/properties/boot_id/type",
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
          if (data.entity_revision !== undefined) {
            let data1 = data.entity_revision;
            const _errs3 = errors;
            if (!(typeof data1 == "number" && !(data1 % 1) && !isNaN(data1))) {
              validate24.errors = [
                {
                  instancePath: instancePath + "/entity_revision",
                  schemaPath: "#/properties/entity_revision/type",
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
            if (data.app_key !== undefined) {
              const _errs5 = errors;
              if (typeof data.app_key !== "string") {
                validate24.errors = [
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
              var valid0 = _errs5 === errors;
            } else {
              var valid0 = true;
            }
            if (valid0) {
              if (data.instance_name !== undefined) {
                const _errs7 = errors;
                if (typeof data.instance_name !== "string") {
                  validate24.errors = [
                    {
                      instancePath: instancePath + "/instance_name",
                      schemaPath: "#/properties/instance_name/type",
                      keyword: "type",
                      params: { type: "string" },
                      message: "must be string",
                    },
                  ];
                  return false;
                }
                var valid0 = _errs7 === errors;
              } else {
                var valid0 = true;
              }
              if (valid0) {
                if (data.entity !== undefined) {
                  let data4 = data.entity;
                  const _errs9 = errors;
                  const _errs10 = errors;
                  if (errors === _errs10) {
                    if (data4 && typeof data4 == "object" && !Array.isArray(data4)) {
                      let missing1;
                      if (
                        (data4.key === undefined && (missing1 = "key")) ||
                        (data4.platform === undefined && (missing1 = "platform")) ||
                        (data4.name === undefined && (missing1 = "name"))
                      ) {
                        validate24.errors = [
                          {
                            instancePath: instancePath + "/entity",
                            schemaPath: "#/$defs/DeclaredEntity/required",
                            keyword: "required",
                            params: { missingProperty: missing1 },
                            message: "must have required property '" + missing1 + "'",
                          },
                        ];
                        return false;
                      } else {
                        if (data4.key !== undefined) {
                          const _errs12 = errors;
                          if (typeof data4.key !== "string") {
                            validate24.errors = [
                              {
                                instancePath: instancePath + "/entity/key",
                                schemaPath: "#/$defs/DeclaredEntity/properties/key/type",
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
                          if (data4.platform !== undefined) {
                            let data6 = data4.platform;
                            const _errs14 = errors;
                            if (typeof data6 !== "string") {
                              validate24.errors = [
                                {
                                  instancePath: instancePath + "/entity/platform",
                                  schemaPath: "#/$defs/DeclaredEntity/properties/platform/type",
                                  keyword: "type",
                                  params: { type: "string" },
                                  message: "must be string",
                                },
                              ];
                              return false;
                            }
                            if (!(data6 === "button" || data6 === "switch" || data6 === "sensor")) {
                              validate24.errors = [
                                {
                                  instancePath: instancePath + "/entity/platform",
                                  schemaPath: "#/$defs/DeclaredEntity/properties/platform/enum",
                                  keyword: "enum",
                                  params: { allowedValues: schema33.properties.platform.enum },
                                  message: "must be equal to one of the allowed values",
                                },
                              ];
                              return false;
                            }
                            var valid2 = _errs14 === errors;
                          } else {
                            var valid2 = true;
                          }
                          if (valid2) {
                            if (data4.name !== undefined) {
                              const _errs16 = errors;
                              if (typeof data4.name !== "string") {
                                validate24.errors = [
                                  {
                                    instancePath: instancePath + "/entity/name",
                                    schemaPath: "#/$defs/DeclaredEntity/properties/name/type",
                                    keyword: "type",
                                    params: { type: "string" },
                                    message: "must be string",
                                  },
                                ];
                                return false;
                              }
                              var valid2 = _errs16 === errors;
                            } else {
                              var valid2 = true;
                            }
                            if (valid2) {
                              if (data4.default_entity_id !== undefined) {
                                let data8 = data4.default_entity_id;
                                const _errs18 = errors;
                                const _errs19 = errors;
                                let valid3 = false;
                                const _errs20 = errors;
                                if (typeof data8 !== "string") {
                                  const err0 = {
                                    instancePath: instancePath + "/entity/default_entity_id",
                                    schemaPath: "#/$defs/DeclaredEntity/properties/default_entity_id/anyOf/0/type",
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
                                var _valid0 = _errs20 === errors;
                                valid3 = valid3 || _valid0;
                                if (!valid3) {
                                  const _errs22 = errors;
                                  if (data8 !== null) {
                                    const err1 = {
                                      instancePath: instancePath + "/entity/default_entity_id",
                                      schemaPath: "#/$defs/DeclaredEntity/properties/default_entity_id/anyOf/1/type",
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
                                  var _valid0 = _errs22 === errors;
                                  valid3 = valid3 || _valid0;
                                }
                                if (!valid3) {
                                  const err2 = {
                                    instancePath: instancePath + "/entity/default_entity_id",
                                    schemaPath: "#/$defs/DeclaredEntity/properties/default_entity_id/anyOf",
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
                                  validate24.errors = vErrors;
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
                                var valid2 = _errs18 === errors;
                              } else {
                                var valid2 = true;
                              }
                              if (valid2) {
                                if (data4.entity_category !== undefined) {
                                  let data9 = data4.entity_category;
                                  const _errs24 = errors;
                                  const _errs25 = errors;
                                  let valid4 = false;
                                  const _errs26 = errors;
                                  if (typeof data9 !== "string") {
                                    const err3 = {
                                      instancePath: instancePath + "/entity/entity_category",
                                      schemaPath: "#/$defs/DeclaredEntity/properties/entity_category/anyOf/0/type",
                                      keyword: "type",
                                      params: { type: "string" },
                                      message: "must be string",
                                    };
                                    if (vErrors === null) {
                                      vErrors = [err3];
                                    } else {
                                      vErrors.push(err3);
                                    }
                                    errors++;
                                  }
                                  var _valid1 = _errs26 === errors;
                                  valid4 = valid4 || _valid1;
                                  if (!valid4) {
                                    const _errs28 = errors;
                                    if (data9 !== null) {
                                      const err4 = {
                                        instancePath: instancePath + "/entity/entity_category",
                                        schemaPath: "#/$defs/DeclaredEntity/properties/entity_category/anyOf/1/type",
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
                                    var _valid1 = _errs28 === errors;
                                    valid4 = valid4 || _valid1;
                                  }
                                  if (!valid4) {
                                    const err5 = {
                                      instancePath: instancePath + "/entity/entity_category",
                                      schemaPath: "#/$defs/DeclaredEntity/properties/entity_category/anyOf",
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
                                    validate24.errors = vErrors;
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
                                  var valid2 = _errs24 === errors;
                                } else {
                                  var valid2 = true;
                                }
                                if (valid2) {
                                  if (data4.icon !== undefined) {
                                    let data10 = data4.icon;
                                    const _errs30 = errors;
                                    const _errs31 = errors;
                                    let valid5 = false;
                                    const _errs32 = errors;
                                    if (typeof data10 !== "string") {
                                      const err6 = {
                                        instancePath: instancePath + "/entity/icon",
                                        schemaPath: "#/$defs/DeclaredEntity/properties/icon/anyOf/0/type",
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
                                    var _valid2 = _errs32 === errors;
                                    valid5 = valid5 || _valid2;
                                    if (!valid5) {
                                      const _errs34 = errors;
                                      if (data10 !== null) {
                                        const err7 = {
                                          instancePath: instancePath + "/entity/icon",
                                          schemaPath: "#/$defs/DeclaredEntity/properties/icon/anyOf/1/type",
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
                                      var _valid2 = _errs34 === errors;
                                      valid5 = valid5 || _valid2;
                                    }
                                    if (!valid5) {
                                      const err8 = {
                                        instancePath: instancePath + "/entity/icon",
                                        schemaPath: "#/$defs/DeclaredEntity/properties/icon/anyOf",
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
                                      validate24.errors = vErrors;
                                      return false;
                                    } else {
                                      errors = _errs31;
                                      if (vErrors !== null) {
                                        if (_errs31) {
                                          vErrors.length = _errs31;
                                        } else {
                                          vErrors = null;
                                        }
                                      }
                                    }
                                    var valid2 = _errs30 === errors;
                                  } else {
                                    var valid2 = true;
                                  }
                                  if (valid2) {
                                    if (data4.unit !== undefined) {
                                      let data11 = data4.unit;
                                      const _errs36 = errors;
                                      const _errs37 = errors;
                                      let valid6 = false;
                                      const _errs38 = errors;
                                      if (typeof data11 !== "string") {
                                        const err9 = {
                                          instancePath: instancePath + "/entity/unit",
                                          schemaPath: "#/$defs/DeclaredEntity/properties/unit/anyOf/0/type",
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
                                      var _valid3 = _errs38 === errors;
                                      valid6 = valid6 || _valid3;
                                      if (!valid6) {
                                        const _errs40 = errors;
                                        if (data11 !== null) {
                                          const err10 = {
                                            instancePath: instancePath + "/entity/unit",
                                            schemaPath: "#/$defs/DeclaredEntity/properties/unit/anyOf/1/type",
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
                                        var _valid3 = _errs40 === errors;
                                        valid6 = valid6 || _valid3;
                                      }
                                      if (!valid6) {
                                        const err11 = {
                                          instancePath: instancePath + "/entity/unit",
                                          schemaPath: "#/$defs/DeclaredEntity/properties/unit/anyOf",
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
                                        validate24.errors = vErrors;
                                        return false;
                                      } else {
                                        errors = _errs37;
                                        if (vErrors !== null) {
                                          if (_errs37) {
                                            vErrors.length = _errs37;
                                          } else {
                                            vErrors = null;
                                          }
                                        }
                                      }
                                      var valid2 = _errs36 === errors;
                                    } else {
                                      var valid2 = true;
                                    }
                                    if (valid2) {
                                      if (data4.device_class !== undefined) {
                                        let data12 = data4.device_class;
                                        const _errs42 = errors;
                                        const _errs43 = errors;
                                        let valid7 = false;
                                        const _errs44 = errors;
                                        if (typeof data12 !== "string") {
                                          const err12 = {
                                            instancePath: instancePath + "/entity/device_class",
                                            schemaPath: "#/$defs/DeclaredEntity/properties/device_class/anyOf/0/type",
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
                                        var _valid4 = _errs44 === errors;
                                        valid7 = valid7 || _valid4;
                                        if (!valid7) {
                                          const _errs46 = errors;
                                          if (data12 !== null) {
                                            const err13 = {
                                              instancePath: instancePath + "/entity/device_class",
                                              schemaPath: "#/$defs/DeclaredEntity/properties/device_class/anyOf/1/type",
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
                                          var _valid4 = _errs46 === errors;
                                          valid7 = valid7 || _valid4;
                                        }
                                        if (!valid7) {
                                          const err14 = {
                                            instancePath: instancePath + "/entity/device_class",
                                            schemaPath: "#/$defs/DeclaredEntity/properties/device_class/anyOf",
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
                                          validate24.errors = vErrors;
                                          return false;
                                        } else {
                                          errors = _errs43;
                                          if (vErrors !== null) {
                                            if (_errs43) {
                                              vErrors.length = _errs43;
                                            } else {
                                              vErrors = null;
                                            }
                                          }
                                        }
                                        var valid2 = _errs42 === errors;
                                      } else {
                                        var valid2 = true;
                                      }
                                      if (valid2) {
                                        if (data4.state_class !== undefined) {
                                          let data13 = data4.state_class;
                                          const _errs48 = errors;
                                          const _errs49 = errors;
                                          let valid8 = false;
                                          const _errs50 = errors;
                                          if (typeof data13 !== "string") {
                                            const err15 = {
                                              instancePath: instancePath + "/entity/state_class",
                                              schemaPath: "#/$defs/DeclaredEntity/properties/state_class/anyOf/0/type",
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
                                          var _valid5 = _errs50 === errors;
                                          valid8 = valid8 || _valid5;
                                          if (!valid8) {
                                            const _errs52 = errors;
                                            if (data13 !== null) {
                                              const err16 = {
                                                instancePath: instancePath + "/entity/state_class",
                                                schemaPath:
                                                  "#/$defs/DeclaredEntity/properties/state_class/anyOf/1/type",
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
                                            var _valid5 = _errs52 === errors;
                                            valid8 = valid8 || _valid5;
                                          }
                                          if (!valid8) {
                                            const err17 = {
                                              instancePath: instancePath + "/entity/state_class",
                                              schemaPath: "#/$defs/DeclaredEntity/properties/state_class/anyOf",
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
                                            validate24.errors = vErrors;
                                            return false;
                                          } else {
                                            errors = _errs49;
                                            if (vErrors !== null) {
                                              if (_errs49) {
                                                vErrors.length = _errs49;
                                              } else {
                                                vErrors = null;
                                              }
                                            }
                                          }
                                          var valid2 = _errs48 === errors;
                                        } else {
                                          var valid2 = true;
                                        }
                                        if (valid2) {
                                          if (data4.options !== undefined) {
                                            let data14 = data4.options;
                                            const _errs54 = errors;
                                            const _errs55 = errors;
                                            let valid9 = false;
                                            const _errs56 = errors;
                                            if (errors === _errs56) {
                                              if (Array.isArray(data14)) {
                                                var valid10 = true;
                                                const len0 = data14.length;
                                                for (let i0 = 0; i0 < len0; i0++) {
                                                  const _errs58 = errors;
                                                  if (typeof data14[i0] !== "string") {
                                                    const err18 = {
                                                      instancePath: instancePath + "/entity/options/" + i0,
                                                      schemaPath:
                                                        "#/$defs/DeclaredEntity/properties/options/anyOf/0/items/type",
                                                      keyword: "type",
                                                      params: { type: "string" },
                                                      message: "must be string",
                                                    };
                                                    if (vErrors === null) {
                                                      vErrors = [err18];
                                                    } else {
                                                      vErrors.push(err18);
                                                    }
                                                    errors++;
                                                  }
                                                  var valid10 = _errs58 === errors;
                                                  if (!valid10) {
                                                    break;
                                                  }
                                                }
                                              } else {
                                                const err19 = {
                                                  instancePath: instancePath + "/entity/options",
                                                  schemaPath: "#/$defs/DeclaredEntity/properties/options/anyOf/0/type",
                                                  keyword: "type",
                                                  params: { type: "array" },
                                                  message: "must be array",
                                                };
                                                if (vErrors === null) {
                                                  vErrors = [err19];
                                                } else {
                                                  vErrors.push(err19);
                                                }
                                                errors++;
                                              }
                                            }
                                            var _valid6 = _errs56 === errors;
                                            valid9 = valid9 || _valid6;
                                            if (!valid9) {
                                              const _errs60 = errors;
                                              if (data14 !== null) {
                                                const err20 = {
                                                  instancePath: instancePath + "/entity/options",
                                                  schemaPath: "#/$defs/DeclaredEntity/properties/options/anyOf/1/type",
                                                  keyword: "type",
                                                  params: { type: "null" },
                                                  message: "must be null",
                                                };
                                                if (vErrors === null) {
                                                  vErrors = [err20];
                                                } else {
                                                  vErrors.push(err20);
                                                }
                                                errors++;
                                              }
                                              var _valid6 = _errs60 === errors;
                                              valid9 = valid9 || _valid6;
                                            }
                                            if (!valid9) {
                                              const err21 = {
                                                instancePath: instancePath + "/entity/options",
                                                schemaPath: "#/$defs/DeclaredEntity/properties/options/anyOf",
                                                keyword: "anyOf",
                                                params: {},
                                                message: "must match a schema in anyOf",
                                              };
                                              if (vErrors === null) {
                                                vErrors = [err21];
                                              } else {
                                                vErrors.push(err21);
                                              }
                                              errors++;
                                              validate24.errors = vErrors;
                                              return false;
                                            } else {
                                              errors = _errs55;
                                              if (vErrors !== null) {
                                                if (_errs55) {
                                                  vErrors.length = _errs55;
                                                } else {
                                                  vErrors = null;
                                                }
                                              }
                                            }
                                            var valid2 = _errs54 === errors;
                                          } else {
                                            var valid2 = true;
                                          }
                                          if (valid2) {
                                            if (data4.value !== undefined) {
                                              let data16 = data4.value;
                                              const _errs62 = errors;
                                              const _errs63 = errors;
                                              let valid11 = false;
                                              const _errs64 = errors;
                                              if (!(typeof data16 == "number" && !(data16 % 1) && !isNaN(data16))) {
                                                const err22 = {
                                                  instancePath: instancePath + "/entity/value",
                                                  schemaPath: "#/$defs/DeclaredEntity/properties/value/anyOf/0/type",
                                                  keyword: "type",
                                                  params: { type: "integer" },
                                                  message: "must be integer",
                                                };
                                                if (vErrors === null) {
                                                  vErrors = [err22];
                                                } else {
                                                  vErrors.push(err22);
                                                }
                                                errors++;
                                              }
                                              var _valid7 = _errs64 === errors;
                                              valid11 = valid11 || _valid7;
                                              if (!valid11) {
                                                const _errs66 = errors;
                                                if (!(typeof data16 == "number")) {
                                                  const err23 = {
                                                    instancePath: instancePath + "/entity/value",
                                                    schemaPath: "#/$defs/DeclaredEntity/properties/value/anyOf/1/type",
                                                    keyword: "type",
                                                    params: { type: "number" },
                                                    message: "must be number",
                                                  };
                                                  if (vErrors === null) {
                                                    vErrors = [err23];
                                                  } else {
                                                    vErrors.push(err23);
                                                  }
                                                  errors++;
                                                }
                                                var _valid7 = _errs66 === errors;
                                                valid11 = valid11 || _valid7;
                                                if (!valid11) {
                                                  const _errs68 = errors;
                                                  if (typeof data16 !== "string") {
                                                    const err24 = {
                                                      instancePath: instancePath + "/entity/value",
                                                      schemaPath:
                                                        "#/$defs/DeclaredEntity/properties/value/anyOf/2/type",
                                                      keyword: "type",
                                                      params: { type: "string" },
                                                      message: "must be string",
                                                    };
                                                    if (vErrors === null) {
                                                      vErrors = [err24];
                                                    } else {
                                                      vErrors.push(err24);
                                                    }
                                                    errors++;
                                                  }
                                                  var _valid7 = _errs68 === errors;
                                                  valid11 = valid11 || _valid7;
                                                  if (!valid11) {
                                                    const _errs70 = errors;
                                                    if (typeof data16 !== "boolean") {
                                                      const err25 = {
                                                        instancePath: instancePath + "/entity/value",
                                                        schemaPath:
                                                          "#/$defs/DeclaredEntity/properties/value/anyOf/3/type",
                                                        keyword: "type",
                                                        params: { type: "boolean" },
                                                        message: "must be boolean",
                                                      };
                                                      if (vErrors === null) {
                                                        vErrors = [err25];
                                                      } else {
                                                        vErrors.push(err25);
                                                      }
                                                      errors++;
                                                    }
                                                    var _valid7 = _errs70 === errors;
                                                    valid11 = valid11 || _valid7;
                                                    if (!valid11) {
                                                      const _errs72 = errors;
                                                      if (data16 !== null) {
                                                        const err26 = {
                                                          instancePath: instancePath + "/entity/value",
                                                          schemaPath:
                                                            "#/$defs/DeclaredEntity/properties/value/anyOf/4/type",
                                                          keyword: "type",
                                                          params: { type: "null" },
                                                          message: "must be null",
                                                        };
                                                        if (vErrors === null) {
                                                          vErrors = [err26];
                                                        } else {
                                                          vErrors.push(err26);
                                                        }
                                                        errors++;
                                                      }
                                                      var _valid7 = _errs72 === errors;
                                                      valid11 = valid11 || _valid7;
                                                    }
                                                  }
                                                }
                                              }
                                              if (!valid11) {
                                                const err27 = {
                                                  instancePath: instancePath + "/entity/value",
                                                  schemaPath: "#/$defs/DeclaredEntity/properties/value/anyOf",
                                                  keyword: "anyOf",
                                                  params: {},
                                                  message: "must match a schema in anyOf",
                                                };
                                                if (vErrors === null) {
                                                  vErrors = [err27];
                                                } else {
                                                  vErrors.push(err27);
                                                }
                                                errors++;
                                                validate24.errors = vErrors;
                                                return false;
                                              } else {
                                                errors = _errs63;
                                                if (vErrors !== null) {
                                                  if (_errs63) {
                                                    vErrors.length = _errs63;
                                                  } else {
                                                    vErrors = null;
                                                  }
                                                }
                                              }
                                              var valid2 = _errs62 === errors;
                                            } else {
                                              var valid2 = true;
                                            }
                                            if (valid2) {
                                              if (data4.attributes !== undefined) {
                                                let data17 = data4.attributes;
                                                const _errs74 = errors;
                                                if (errors === _errs74) {
                                                  if (data17 && typeof data17 == "object" && !Array.isArray(data17)) {
                                                  } else {
                                                    validate24.errors = [
                                                      {
                                                        instancePath: instancePath + "/entity/attributes",
                                                        schemaPath: "#/$defs/DeclaredEntity/properties/attributes/type",
                                                        keyword: "type",
                                                        params: { type: "object" },
                                                        message: "must be object",
                                                      },
                                                    ];
                                                    return false;
                                                  }
                                                }
                                                var valid2 = _errs74 === errors;
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
                    } else {
                      validate24.errors = [
                        {
                          instancePath: instancePath + "/entity",
                          schemaPath: "#/$defs/DeclaredEntity/type",
                          keyword: "type",
                          params: { type: "object" },
                          message: "must be object",
                        },
                      ];
                      return false;
                    }
                  }
                  var valid0 = _errs9 === errors;
                } else {
                  var valid0 = true;
                }
              }
            }
          }
        }
      }
    } else {
      validate24.errors = [
        { instancePath, schemaPath: "#/type", keyword: "type", params: { type: "object" }, message: "must be object" },
      ];
      return false;
    }
  }
  validate24.errors = vErrors;
  return errors === 0;
}
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
          if ("entity_state_changed" !== data0) {
            validate23.errors = [
              {
                instancePath: instancePath + "/type",
                schemaPath: "#/properties/type/const",
                keyword: "const",
                params: { allowedValue: "entity_state_changed" },
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
              !validate24(data.data, {
                instancePath: instancePath + "/data",
                parentData: data,
                parentDataProperty: "data",
                rootData,
              })
            ) {
              vErrors = vErrors === null ? validate24.errors : vErrors.concat(validate24.errors);
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
              var valid0 = _errs4 === errors;
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
        } else if (tag0 === "log_hint") {
          const _errs3 = errors;
          if (errors === _errs3) {
            if (data && typeof data == "object" && !Array.isArray(data)) {
              let missing0;
              if (
                (data.type === undefined && (missing0 = "type")) ||
                (data.timestamp === undefined && (missing0 = "timestamp"))
              ) {
                validate10.errors = [
                  {
                    instancePath,
                    schemaPath: "#/$defs/LogHintWsMessage/required",
                    keyword: "required",
                    params: { missingProperty: missing0 },
                    message: "must have required property '" + missing0 + "'",
                  },
                ];
                return false;
              } else {
                if (data.type !== undefined) {
                  let data0 = data.type;
                  const _errs5 = errors;
                  if (typeof data0 !== "string") {
                    validate10.errors = [
                      {
                        instancePath: instancePath + "/type",
                        schemaPath: "#/$defs/LogHintWsMessage/properties/type/type",
                        keyword: "type",
                        params: { type: "string" },
                        message: "must be string",
                      },
                    ];
                    return false;
                  }
                  if ("log_hint" !== data0) {
                    validate10.errors = [
                      {
                        instancePath: instancePath + "/type",
                        schemaPath: "#/$defs/LogHintWsMessage/properties/type/const",
                        keyword: "const",
                        params: { allowedValue: "log_hint" },
                        message: "must be equal to constant",
                      },
                    ];
                    return false;
                  }
                  var valid4 = _errs5 === errors;
                } else {
                  var valid4 = true;
                }
                if (valid4) {
                  if (data.timestamp !== undefined) {
                    const _errs7 = errors;
                    if (!(typeof data.timestamp == "number")) {
                      validate10.errors = [
                        {
                          instancePath: instancePath + "/timestamp",
                          schemaPath: "#/$defs/LogHintWsMessage/properties/timestamp/type",
                          keyword: "type",
                          params: { type: "number" },
                          message: "must be number",
                        },
                      ];
                      return false;
                    }
                    var valid4 = _errs7 === errors;
                  } else {
                    var valid4 = true;
                  }
                }
              }
            } else {
              validate10.errors = [
                {
                  instancePath,
                  schemaPath: "#/$defs/LogHintWsMessage/type",
                  keyword: "type",
                  params: { type: "object" },
                  message: "must be object",
                },
              ];
              return false;
            }
          }
        } else if (tag0 === "connected") {
          if (!validate14(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate14.errors : vErrors.concat(validate14.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "connectivity") {
          if (!validate15(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate15.errors : vErrors.concat(validate15.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "service_status") {
          if (!validate16(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate16.errors : vErrors.concat(validate16.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "execution_completed") {
          if (!validate19(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate19.errors : vErrors.concat(validate19.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "apps_changed") {
          if (!validate22(data, { instancePath, parentData, parentDataProperty, rootData })) {
            vErrors = vErrors === null ? validate22.errors : vErrors.concat(validate22.errors);
            errors = vErrors.length;
          }
        } else if (tag0 === "entity_state_changed") {
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
