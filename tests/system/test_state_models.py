"""Every registered state model must convert what the pinned Home Assistant actually publishes.

The test drives the helper entities in ``tests/fixtures/ha-config/configuration.yaml`` through the
transitions that populate their conditional attributes, collects every state it observes (each
``state_changed`` new/old state during the drive, plus a final ``get_states`` snapshot), and then
judges that one set three ways:

1. Conversion: every observed state in a registered domain converts to its registered class through
   the strict path. ``try_convert_state``'s ``BaseState`` fallback is never used, so a mistyped
   attribute fails here instead of silently degrading.
2. Domain gate: every registered domain has at least one observed state, unless it is on
   ``DOMAIN_ALLOWLIST``. An allowlisted domain that is now observed fails as stale.
3. Attribute gate: every hand-typed attribute is seen with a non-null value at least once, under
   any key its field accepts, unless it is on ``ATTRIBUTE_ALLOWLIST``. Hand-typed means every
   attribute of a model whose file is not codegen output or whose codegen override is
   ``discovery = "manual"``, plus each field a ``[[property_overrides]]`` entry renames, retypes or
   aliases in a discovered model. Attribute entries are not stale-checked: demo entities change on
   their own, so whether an attribute appears varies between runs.

Allowlisted domains and attributes stay unverified. Domains with no registered model are ignored;
``hassette-codegen check-coverage`` reports those.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import pytest
from hassette_codegen.manifest import load_manifest, manifest_exists
from hassette_codegen.overrides import load_overrides
from pydantic import AliasChoices

import hassette
from hassette import STATE_REGISTRY
from hassette.api import Api
from hassette.conversion.state_registry import convert_state_dict_to_model
from hassette.events import HassStateDict, RawStateChangeEvent
from hassette.models.states.base import AttributesBase, BaseState
from hassette.testing import wait_for

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(hassette.__file__).resolve().parent
PACKAGE_ROOT_IN_REPO = Path("src") / "hassette"
TRANSITION_TIMEOUT_SECONDS = 15.0

TIMER = "timer.state_model"
SCRIPT = "script.state_model"

DOMAIN_ALLOWLIST: dict[str, str] = {
    "ai_task": "needs an AI provider integration; nothing offline provides one",
    "assist_satellite": "needs a voice satellite device",
    "image": "the demo integration has no image platform",
    "infrared": "needs an infrared transmitter integration",
    "lawn_mower": "the demo integration has no lawn_mower platform",
    "radio_frequency": "needs a radio-frequency transmitter integration",
    "tag": "tags are created through the tag WebSocket collection, not YAML config",
    "tts": "the demo tts platform is a legacy provider, which creates no tts entity",
    "wake_word": "needs a wake-word engine integration",
}
"""Registered domains the system HA cannot provide, each with the reason. A domain that becomes
observed fails the test as stale, so remove its entry."""

DEMO_AIR_QUALITY = "the demo air_quality entities don't publish this pollutant"
LEGACY_TRACKER = "the demo device trackers are legacy GPS trackers; only modern tracker entities publish this"
DEMO_FACE_DETECTION = "the demo face-detection entities don't publish it"
DEMO_WEATHER = "the demo weather entities don't publish it"
DEMO_WATER_HEATER = "the demo water heaters publish it as null"
NOT_AN_ATTRIBUTE = "HA never publishes it as a state attribute"
WRONG_WIRE_KEY = "known model bug #3799: HA publishes it under a different key, so it stays None"

ATTRIBUTE_ALLOWLIST: dict[str, dict[str, str]] = {
    "climate": {
        "hvac_mode": "HA publishes the HVAC mode as the state, not an attribute",
        "target_temp_step": "no demo climate entity sets a target temperature step",
        "temperature_unit": NOT_AN_ATTRIBUTE,
    },
    "cover": dict.fromkeys(("current_cover_position", "current_cover_tilt_position"), WRONG_WIRE_KEY),
    "event": {"event_type": "set only once the event entity fires, which nothing in the drive can trigger"},
    "number": dict.fromkeys(("max_value", "min_value"), WRONG_WIRE_KEY),
    "water_heater": {
        **dict.fromkeys(
            ("current_temperature", "target_temperature_high", "target_temperature_low"), DEMO_WATER_HEATER
        ),
        "temperature_unit": NOT_AN_ATTRIBUTE,
    },
    "weather": dict.fromkeys(
        ("apparent_temperature", "cloud_coverage", "dew_point", "visibility", "wind_gust_speed"), DEMO_WEATHER
    ),
    "air_quality": dict.fromkeys(
        (
            "air_quality_index",
            "carbon_dioxide",
            "carbon_monoxide",
            "nitrogen_dioxide",
            "nitrogen_monoxide",
            "ozone",
            "particulate_matter_0_1",
            "sulphur_dioxide",
        ),
        DEMO_AIR_QUALITY,
    ),
    "device_tracker": dict.fromkeys(("battery_level", "host_name", "in_zones", "ip", "mac"), LEGACY_TRACKER),
    "group": {"auto": "HA sets it only on groups it generates itself; a YAML group never carries it"},
    "image_processing": dict.fromkeys(("camera_entity", "confidence"), DEMO_FACE_DETECTION),
}
"""Hand-typed attributes the drive cannot populate, keyed by domain, each with the reason. An entry
naming an issue is a known model bug: remove it when the issue is fixed."""


@dataclass(frozen=True)
class Expect:
    """A predicate over a raw state, with the description a timeout reports."""

    desc: str
    check: Callable[[HassStateDict], bool]


def state_is(value: str, note: str = "") -> Expect:
    return Expect(f"{value} {note}".strip(), lambda s: s["state"] == value)


def state_known(desc: str) -> Expect:
    return Expect(desc, lambda s: s["state"] != "unknown")


def attribute_set(name: str) -> Expect:
    return Expect(f"{name} set", lambda s: s["attributes"].get(name) is not None)


@dataclass(frozen=True)
class DriveStep:
    """One service call and the state that shows it took effect."""

    domain: str
    service: str
    entity_id: str
    expect: Expect
    data: dict[str, Any] = field(default_factory=dict)


DRIVE: list[DriveStep] = [
    DriveStep("timer", "start", TIMER, state_is("active")),
    DriveStep("timer", "pause", TIMER, state_is("paused")),
    DriveStep("timer", "start", TIMER, state_is("active", "(resumed)")),
    # HA ignores timer.finish on an idle timer, so it is only ever issued on an active one.
    DriveStep("timer", "finish", TIMER, state_is("idle", "(finished)")),
    DriveStep("timer", "start", TIMER, state_is("active", "(restarted)")),
    DriveStep("timer", "cancel", TIMER, state_is("idle", "(cancelled)")),
    DriveStep("counter", "increment", "counter.state_model", state_is("1")),
    DriveStep("input_number", "set_value", "input_number.state_model", state_is("25.0"), {"value": 25}),
    DriveStep("input_select", "select_option", "input_select.state_model", state_is("second"), {"option": "second"}),
    DriveStep("input_text", "set_value", "input_text.state_model", state_is("abc"), {"value": "abc"}),
    DriveStep(
        "input_datetime",
        "set_datetime",
        "input_datetime.state_model",
        state_is("2026-01-02 03:04:05"),
        {"datetime": "2026-01-02 03:04:05"},
    ),
    DriveStep("input_button", "press", "input_button.state_model", state_known("pressed")),
    DriveStep("scene", "turn_on", "scene.state_model_scene", state_known("activated")),
    # The script holds on a long delay, publishing last_action while it runs, until turned off.
    DriveStep("script", "turn_on", SCRIPT, attribute_set("last_action")),
    DriveStep("script", "turn_off", SCRIPT, state_is("off")),
    DriveStep("automation", "trigger", "automation.state_model_automation", attribute_set("last_triggered")),
    DriveStep("fan", "set_percentage", "fan.living_room_fan", attribute_set("percentage"), {"percentage": 50}),
    DriveStep(
        "camera",
        "enable_motion_detection",
        "camera.demo_camera",
        Expect("motion_detection on", lambda s: s["attributes"].get("motion_detection") is True),
    ),
]
"""Service calls that populate conditional attributes, in order. Each waits for its expected state."""


@dataclass(frozen=True)
class ObservedState:
    """A raw state the test saw: its kind, the drive step it arrived during, and the state itself."""

    kind: Literal["new", "old", "snapshot"]
    step: str
    state: HassStateDict

    @property
    def entity_id(self) -> str:
        return self.state["entity_id"]

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]


@dataclass
class StateRecorder:
    """Collects every observed state, labelled with the drive step running when it arrived.

    A late event can carry the next step's label; the label only feeds failure messages.
    """

    step: str = "startup"
    observed: list[ObservedState] = field(default_factory=list)

    async def record(self, event: RawStateChangeEvent) -> None:
        data = event.payload.data
        if data.new_state is not None:
            self.observed.append(ObservedState("new", self.step, data.new_state))
        if data.old_state is not None:
            self.observed.append(ObservedState("old", self.step, data.old_state))

    async def wait_for_new_state(self, start: int, entity_id: str, expect: Expect) -> None:
        """Wait until a new state recorded at or after index `start` is `entity_id` matching `expect`.

        Old states are never matched: they are what the entity left, not what the call produced.
        """
        await wait_for(
            lambda: any(
                o.kind == "new" and o.entity_id == entity_id and expect.check(o.state) for o in self.observed[start:]
            ),
            timeout=TRANSITION_TIMEOUT_SECONDS,
            desc=f"{entity_id} to reach {expect.desc}",
        )

    async def run_step(self, api: Api, step: DriveStep) -> None:
        self.step = f"{step.domain}.{step.service} on {step.entity_id}"
        start = len(self.observed)
        await api.call_service(step.domain, step.service, {"entity_id": step.entity_id}, wait_for_ack=True, **step.data)
        await self.wait_for_new_state(start, step.entity_id, step.expect)


# The drive mutates helpers on the session-scoped HA and isn't idempotent, so a rerun would time out
# on the helpers the first attempt already moved and report that instead of the real failure.
@pytest.mark.flaky(reruns=0)
async def test_live_states_convert_to_registered_models(ha_container: str, tmp_path: Path) -> None:
    """Every observed state converts strictly, and the coverage gates pass."""
    config = make_system_config(ha_container, tmp_path)
    recorder = StateRecorder()

    async with startup_context(config) as hassette:
        # changed=False keeps attribute-only changes (a timer's remaining, an automation's
        # last_triggered); parallel mode never drops an event that arrives mid-handler.
        await hassette.bus.on_state_change(
            "*", handler=recorder.record, changed=False, mode="parallel", name="state_models"
        )

        for step in DRIVE:
            await recorder.run_step(hassette.api, step)

        recorder.observed.extend(ObservedState("snapshot", "snapshot", s) for s in await hassette.api.get_states_raw())

    observed = recorder.observed
    models = shipped_models()
    failures = [
        *conversion_failures(observed, models),
        *domain_gate_failures(observed, models),
        *attribute_gate_failures(observed, models),
    ]
    assert not failures, f"{len(failures)} state model check(s) failed:\n" + "\n".join(failures)


def shipped_models() -> dict[str, type[BaseState]]:
    """Registered models defined inside the hassette package, keyed by domain.

    The registry is process-global: test modules that define a state class at import (pytest
    imports every module before filtering by marker) register it too. Those aren't models
    hassette ships, so they are left out.
    """
    return {
        str(key.domain): cls
        for key, cls in STATE_REGISTRY.items()
        if Path(inspect.getfile(cls)).resolve().is_relative_to(PACKAGE_ROOT)
    }


def conversion_failures(observed: list[ObservedState], models: dict[str, type[BaseState]]) -> list[str]:
    """Convert each observed state in a registered domain to its class, with no fallback."""
    failures: list[str] = []
    for o in observed:
        state_cls = models.get(o.domain)
        if state_cls is None:
            continue
        try:
            convert_state_dict_to_model(o.state, state_cls)
        except Exception as exc:
            # The conversion layer wraps the pydantic ValidationError, which names the bad field.
            cause = exc.__cause__ or exc
            failures.append(
                f"conversion: {o.entity_id} ({o.kind} state, during {o.step}) state={o.state['state']!r} "
                f"failed as {state_cls.__name__}: {cause}"
            )
    return failures


def domain_gate_failures(observed: list[ObservedState], models: dict[str, type[BaseState]]) -> list[str]:
    """Registered domains with no observed state, and allowlist entries that are stale or unknown."""
    seen = {o.domain for o in observed}
    unobserved = sorted(set(models) - seen - set(DOMAIN_ALLOWLIST))
    stale = sorted(set(DOMAIN_ALLOWLIST) & seen)
    unknown = sorted(set(DOMAIN_ALLOWLIST) - set(models))
    return [
        *(
            f"domain gate: no live {domain} state; add entities for it to the system HA config "
            "or allowlist it in DOMAIN_ALLOWLIST with a reason"
            for domain in unobserved
        ),
        *(f"domain gate: {domain} is observed now; remove its DOMAIN_ALLOWLIST entry" for domain in stale),
        *(f"domain gate: DOMAIN_ALLOWLIST entry {domain} is not a registered domain" for domain in unknown),
    ]


def attribute_gate_failures(observed: list[ObservedState], models: dict[str, type[BaseState]]) -> list[str]:
    """Hand-typed attributes that no observed state carried with a value under any key the field accepts."""
    seen: dict[str, set[str]] = {}
    for o in observed:
        attrs = o.state.get("attributes") or {}
        seen.setdefault(o.domain, set()).update(name for name, value in attrs.items() if value is not None)

    failures: list[str] = []
    for domain, fields in sorted(hand_typed_attributes(models).items()):
        if domain in DOMAIN_ALLOWLIST or domain not in seen:
            continue  # the domain gate already reports an unobserved domain
        allowed = ATTRIBUTE_ALLOWLIST.get(domain, {})
        failures.extend(
            f"attribute gate: {domain}.{name} never observed with a value; drive an entity that publishes it "
            "or allowlist it in ATTRIBUTE_ALLOWLIST with a reason"
            for name, keys in sorted(fields.items())
            if name not in allowed and not keys & seen[domain]
        )
    return failures


def hand_typed_attributes(models: dict[str, type[BaseState]]) -> dict[str, dict[str, set[str]]]:
    """The attributes whose types or wire keys are hand-declared, per domain: field name to accepted keys.

    A whole model is hand-typed when its module is not codegen output (absent from codegen's
    manifest) or its domain's codegen override sets ``discovery = "manual"``. In a discovered
    model, only the fields a ``[[property_overrides]]`` entry renames, retypes or aliases are.
    Module paths are taken relative to the installed package, so this holds whether or not
    hassette is installed editable.
    """
    assert manifest_exists(REPO_ROOT), "no codegen manifest: every model would count as hand-typed"
    generated = load_manifest(REPO_ROOT)
    overrides = load_overrides()
    result: dict[str, dict[str, set[str]]] = {}
    for domain, cls in models.items():
        fields = declared_attributes(cls)
        override = overrides.get(domain)
        module = PACKAGE_ROOT_IN_REPO / Path(inspect.getfile(cls)).resolve().relative_to(PACKAGE_ROOT)
        if module not in generated or (override is not None and override.discovery == "manual"):
            result[domain] = fields
        elif override is not None:
            overridden = {o.wire_name or o.name for o in override.property_overrides if not o.remove}
            if picked := {name: keys for name, keys in fields.items() if name in overridden}:
                result[domain] = picked
    # Canary on the derivation: timer, script and automation are hand-typed only through their
    # manual overrides, climate's fields only through property overrides, and light's fields are
    # never all hand-typed. A codegen move that silently empties a source would otherwise shrink
    # the attribute gate while the test stays green.
    assert {"timer", "script", "automation", "climate"} <= set(result), f"overrides not found: {sorted(overrides)}"
    light = set(result.get("light", {}))
    assert light != set(declared_attributes(models["light"])), "codegen manifest not matched: light is all hand-typed"
    return result


def declared_attributes(state_cls: type[BaseState]) -> dict[str, set[str]]:
    """Attributes the model declares beyond ``AttributesBase``: field name to every key HA may publish it under."""
    attrs_cls = state_cls.model_fields["attributes"].annotation
    assert isinstance(attrs_cls, type), state_cls
    assert issubclass(attrs_cls, AttributesBase), state_cls
    result: dict[str, set[str]] = {}
    for name, info in attrs_cls.model_fields.items():
        if name in AttributesBase.model_fields:
            continue
        keys = {info.alias or name}
        if isinstance(info.validation_alias, AliasChoices):
            keys.update(choice for choice in info.validation_alias.choices if isinstance(choice, str))
        elif isinstance(info.validation_alias, str):
            keys.add(info.validation_alias)
        result[name] = keys
    return result
