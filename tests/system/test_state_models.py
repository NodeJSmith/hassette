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
3. Attribute gate: for hand-typed models (their file is not codegen output, or their codegen
   override is ``discovery = "manual"``), every declared attribute is seen with a non-null value at
   least once, unless it is on ``ATTRIBUTE_ALLOWLIST``. Attribute entries are not stale-checked:
   demo entities change on their own, so whether an attribute appears varies between runs.

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
AUTOMATION = "automation.state_model_automation"
# The script waits on RELEASE, the automation turns it back off, and the alert fires while it's on.
RELEASE = "input_boolean.state_model_release"

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

ATTRIBUTE_ALLOWLIST: dict[str, dict[str, str]] = {
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
"""Hand-typed attributes the drive cannot populate, keyed by domain, each with the reason."""


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
    # The script stays running until RELEASE turns on. last_action appears once the run reaches
    # its wait step, which keeps the release from racing a script that hasn't started waiting.
    DriveStep("script", "turn_on", SCRIPT, attribute_set("last_action")),
    # Must stay last: RELEASE_EFFECTS are waited on from the moment it runs.
    DriveStep("input_boolean", "turn_on", RELEASE, state_is("on")),
]
"""Service calls that populate conditional attributes, in order. Each waits for its expected state."""

RELEASE_EFFECTS: list[tuple[str, Expect]] = [
    (SCRIPT, state_is("off", "(released)")),
    (AUTOMATION, attribute_set("last_triggered")),
    (RELEASE, state_is("off", "(reset by the automation)")),
]
"""What the last drive step causes on other entities, waited on before the snapshot."""


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

        *setup_steps, release_step = DRIVE
        assert release_step.entity_id == RELEASE, "the last DRIVE step must turn RELEASE on"
        for step in setup_steps:
            await recorder.run_step(hassette.api, step)
        release_start = len(recorder.observed)
        await recorder.run_step(hassette.api, release_step)
        for entity_id, expect in RELEASE_EFFECTS:
            await recorder.wait_for_new_state(release_start, entity_id, expect)

        recorder.observed.extend(ObservedState("snapshot", "snapshot", s) for s in await hassette.api.get_states_raw())

    observed = recorder.observed
    models = {str(key.domain): cls for key, cls in STATE_REGISTRY.items()}
    failures = [
        *conversion_failures(observed, models),
        *domain_gate_failures(observed, models),
        *attribute_gate_failures(observed, models),
    ]
    assert not failures, f"{len(failures)} state model check(s) failed:\n" + "\n".join(failures)


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
    """Declared attributes of hand-typed models that no observed state carried with a value."""
    seen: dict[str, set[str]] = {}
    for o in observed:
        attrs = o.state.get("attributes") or {}
        seen.setdefault(o.domain, set()).update(name for name, value in attrs.items() if value is not None)

    failures: list[str] = []
    for domain in sorted(hand_typed_domains(models)):
        if domain in DOMAIN_ALLOWLIST or domain not in seen:
            continue  # the domain gate already reports an unobserved domain
        allowed = ATTRIBUTE_ALLOWLIST.get(domain, {})
        missing = sorted(declared_attributes(models[domain]) - seen[domain] - set(allowed))
        failures.extend(
            f"attribute gate: {domain}.{name} never observed with a value; drive an entity that publishes it "
            "or allowlist it in ATTRIBUTE_ALLOWLIST with a reason"
            for name in missing
        )
    return failures


def hand_typed_domains(models: dict[str, type[BaseState]]) -> set[str]:
    """Domains whose model types are hand-declared rather than taken from HA source annotations.

    A model is hand-typed when its module is not codegen output (absent from codegen's manifest)
    or its domain's codegen override sets ``discovery = "manual"``. Module paths are taken relative
    to the installed package, so this holds whether or not hassette is installed editable.
    """
    assert manifest_exists(REPO_ROOT), "no codegen manifest: every model would count as hand-typed"
    generated = load_manifest(REPO_ROOT)
    manual = {domain for domain, override in load_overrides().items() if override.discovery == "manual"}
    return {
        domain
        for domain, cls in models.items()
        if domain in manual
        or PACKAGE_ROOT_IN_REPO / Path(inspect.getfile(cls)).resolve().relative_to(PACKAGE_ROOT) not in generated
    }


def declared_attributes(state_cls: type[BaseState]) -> set[str]:
    """Attribute keys the model declares beyond ``AttributesBase``, by the name HA publishes."""
    attrs_cls = state_cls.model_fields["attributes"].annotation
    assert isinstance(attrs_cls, type), state_cls
    assert issubclass(attrs_cls, AttributesBase), state_cls
    return {
        info.alias or name for name, info in attrs_cls.model_fields.items() if name not in AttributesBase.model_fields
    }
