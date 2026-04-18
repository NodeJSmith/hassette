"""SimulationMixin — event simulation helpers for AppTestHarness.

Contains all ``simulate_*`` methods and the internal ``_drain_task_bucket``
machinery extracted from ``app_harness.py``.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from hassette.events.hassette import HassetteAppStateEvent, HassetteServiceEvent, HassetteSimpleEvent
from hassette.types import ResourceRole, ResourceStatus, Topic

if TYPE_CHECKING:
    from hassette.app.app import App
    from hassette.core.bus_service import BusService
    from hassette.test_utils.harness import HassetteHarness

from hassette.test_utils.exceptions import DrainError, DrainTimeout
from hassette.test_utils.helpers import (
    _create_component_loaded_event,
    _create_service_registered_event,
    create_call_service_event,
    create_state_change_event,
)

LOGGER = logging.getLogger(__name__)


class SimulationMixin:
    """Mixin providing event simulation and drain mechanics for ``AppTestHarness``.

    Depends on the host providing ``_harness``, ``_app``, and ``bus`` —
    declared as class-level annotations below, satisfied by ``AppTestHarness``.
    """

    # Provided by AppTestHarness; declared here for type narrowing within the mixin.
    _harness: "HassetteHarness | None"
    _app: "App | None"

    def _require_harness(self) -> "HassetteHarness":
        """Return the active HassetteHarness or raise RuntimeError.

        Centralises the ``if harness is None: raise RuntimeError(...)`` guard
        that was previously duplicated at 5+ call sites.

        Returns:
            The active HassetteHarness.

        Raises:
            RuntimeError: If the harness is not active (i.e., called outside
                ``async with AppTestHarness(...) as harness:``).
        """
        harness = self._harness
        if harness is None:
            raise RuntimeError("AppTestHarness is not active")
        return harness

    async def simulate_state_change(
        self,
        entity_id: str,
        *,
        old_value: Any,
        new_value: Any,
        old_attrs: dict | None = None,
        new_attrs: dict | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Create a state change event and send it through the bus.

        Waits for all triggered handlers to complete by polling the task bucket
        until empty, with a configurable timeout.

        Args:
            entity_id: The entity ID that changed.
            old_value: Previous state value.
            new_value: New state value.
            old_attrs: Previous attributes dict (optional).
            new_attrs: New attributes dict (optional).
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler raised an exception.
            DrainTimeout: If drain does not reach quiescence within ``timeout``.
        """
        harness = self._require_harness()

        event = create_state_change_event(
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            old_attrs=old_attrs,
            new_attrs=new_attrs,
        )
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_attribute_change(
        self,
        entity_id: str,
        attribute: str,
        *,
        old_value: Any,
        new_value: Any,
        state: str | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Create an attribute change event and send it through the bus.

        Delegates to :meth:`simulate_state_change`, so any ``on_state_change``
        handler for the same entity will also fire (matching HA behavior).

        State value resolution order: explicit ``state`` arg, cached proxy value,
        ``"unknown"`` fallback. Call :meth:`set_state` first to avoid the fallback.

        Args:
            entity_id: The entity ID whose attribute changed.
            attribute: The attribute name.
            old_value: Previous attribute value.
            new_value: New attribute value.
            state: Explicit state value; if omitted, uses cached value or ``"unknown"``.
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler raised an exception.
            DrainTimeout: If drain does not reach quiescence within ``timeout``.
        """
        harness = self._require_harness()

        if state is not None:
            current_state = state
        else:
            state_proxy = harness.hassette._state_proxy
            if state_proxy is not None:
                # Lock-free read is safe: dict.get() is atomic in CPython, consistent
                # with StateProxy.get_state()'s documented lock-free read pattern.
                raw = state_proxy.states.get(entity_id)
                current_state = raw["state"] if raw is not None else "unknown"
            else:
                current_state = "unknown"

        await self.simulate_state_change(
            entity_id,
            old_value=current_state,
            new_value=current_state,
            old_attrs={attribute: old_value},
            new_attrs={attribute: new_value},
            timeout=timeout,
        )

    async def simulate_call_service(
        self,
        domain: str,
        service: str,
        timeout: float = 2.0,
        **data: Any,
    ) -> None:
        """Create a call_service event and send it through the bus.

        Args:
            domain: Service domain (e.g., "light").
            service: Service name (e.g., "turn_on").
            timeout: Maximum seconds to wait for handlers to complete.
            **data: Service call data.

        Raises:
            DrainError: If any handler raised an exception.
            DrainTimeout: If drain does not reach quiescence within ``timeout``.
        """
        harness = self._require_harness()

        event = create_call_service_event(domain=domain, service=service, service_data=data)
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_component_loaded(
        self,
        component: str,
        timeout: float = 2.0,
    ) -> None:
        """Create a component_loaded event and send it through the bus.

        Args:
            component: The component name (e.g., "mqtt", "zwave").
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler task raised a non-cancellation exception.
            DrainTimeout: If the drain does not reach quiescence within ``timeout``.
        """
        harness = self._require_harness()

        event = _create_component_loaded_event(component)
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_service_registered(
        self,
        domain: str,
        service: str,
        timeout: float = 2.0,
    ) -> None:
        """Create a service_registered event and send it through the bus.

        Args:
            domain: Service domain (e.g., "light").
            service: Service name (e.g., "turn_on").
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler task raised a non-cancellation exception.
            DrainTimeout: If the drain does not reach quiescence within ``timeout``.
        """
        harness = self._require_harness()

        event = _create_service_registered_event(domain, service)
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_hassette_service_status(
        self,
        resource_name: str,
        status: ResourceStatus,
        *,
        role: ResourceRole = ResourceRole.SERVICE,
        previous_status: ResourceStatus | None = None,
        exception: Exception | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Create a Hassette service status event and send it through the bus.

        Args:
            resource_name: Name of the service (e.g., "WebSocketService").
            status: The new status of the service.
            role: The resource role. Defaults to ``ResourceRole.SERVICE``.
            previous_status: The previous status, if known.
            exception: An exception associated with the status change, if any.
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler raised an exception.
            DrainTimeout: If drain does not reach quiescence within ``timeout``.

        Note:
            Only ``app.task_bucket`` is drained — see :meth:`_drain_task_bucket`.
        """
        harness = self._require_harness()

        event = HassetteServiceEvent.from_data(
            resource_name=resource_name,
            role=role,
            status=status,
            previous_status=previous_status,
            exception=exception,
        )
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_hassette_service_failed(
        self,
        resource_name: str,
        *,
        exception: Exception | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Convenience: simulate a service reaching FAILED status.

        Delegates to :meth:`simulate_hassette_service_status`.
        """
        await self.simulate_hassette_service_status(
            resource_name, ResourceStatus.FAILED, exception=exception, timeout=timeout
        )

    async def simulate_hassette_service_crashed(
        self,
        resource_name: str,
        *,
        exception: Exception | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Convenience: simulate a service reaching CRASHED status.

        Delegates to :meth:`simulate_hassette_service_status`.
        """
        await self.simulate_hassette_service_status(
            resource_name, ResourceStatus.CRASHED, exception=exception, timeout=timeout
        )

    async def simulate_hassette_service_started(
        self,
        resource_name: str,
        *,
        timeout: float = 2.0,
    ) -> None:
        """Convenience: simulate a service reaching RUNNING status.

        Delegates to :meth:`simulate_hassette_service_status`.
        """
        await self.simulate_hassette_service_status(resource_name, ResourceStatus.RUNNING, timeout=timeout)

    async def simulate_websocket_connected(
        self,
        timeout: float = 2.0,
    ) -> None:
        """Create a websocket connected event and send it through the bus.

        Args:
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler raised an exception.
            DrainTimeout: If drain does not reach quiescence within ``timeout``.

        Note:
            Only ``app.task_bucket`` is drained — see :meth:`_drain_task_bucket`.
        """
        harness = self._require_harness()

        event = HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_websocket_disconnected(
        self,
        timeout: float = 2.0,
    ) -> None:
        """Create a websocket disconnected event and send it through the bus.

        Args:
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler raised an exception.
            DrainTimeout: If drain does not reach quiescence within ``timeout``.

        Note:
            Only ``app.task_bucket`` is drained — see :meth:`_drain_task_bucket`.
        """
        harness = self._require_harness()

        event = HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED)
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_app_state_changed(
        self,
        status: ResourceStatus,
        *,
        previous_status: ResourceStatus | None = None,
        exception: Exception | None = None,
        timeout: float = 2.0,
    ) -> None:
        """Create an app state changed event and send it through the bus.

        Always emits for the harness's own app. For cross-app coordination tests,
        construct ``HassetteAppStateEvent`` manually and call
        ``harness._harness.hassette.send_event(...)`` directly.

        Args:
            status: The new app status.
            previous_status: The previous status, if known.
            exception: An exception associated with the status change, if any.
            timeout: Maximum seconds to wait for handlers to complete.

        Raises:
            DrainError: If any handler raised an exception.
            DrainTimeout: If drain does not reach quiescence within ``timeout``.

        Note:
            Only ``app.task_bucket`` is drained — see :meth:`_drain_task_bucket`.
        """
        harness = self._require_harness()
        app = self._app
        if app is None:
            raise RuntimeError("AppTestHarness is not active — no app available")

        event = HassetteAppStateEvent.from_data(
            app=app,
            status=status,
            previous_status=previous_status,
            exception=exception,
        )
        await harness.hassette.send_event(event.topic, event)
        await self._drain_task_bucket(timeout=timeout)

    async def simulate_app_running(
        self,
        *,
        timeout: float = 2.0,
    ) -> None:
        """Convenience: simulate the app reaching RUNNING status.

        Delegates to :meth:`simulate_app_state_changed`.
        """
        await self.simulate_app_state_changed(ResourceStatus.RUNNING, timeout=timeout)

    async def simulate_app_stopping(
        self,
        *,
        timeout: float = 2.0,
    ) -> None:
        """Convenience: simulate the app reaching STOPPING status.

        Delegates to :meth:`simulate_app_state_changed`.
        """
        await self.simulate_app_state_changed(ResourceStatus.STOPPING, timeout=timeout)

    async def simulate_homeassistant_restart(
        self,
        timeout: float = 2.0,
    ) -> None:
        """Convenience: simulate a homeassistant restart call_service event.

        Delegates to :meth:`simulate_call_service`.
        """
        await self.simulate_call_service("homeassistant", "restart", timeout=timeout)

    async def simulate_homeassistant_start(
        self,
        timeout: float = 2.0,
    ) -> None:
        """Convenience: simulate a homeassistant start call_service event.

        Delegates to :meth:`simulate_call_service`.
        """
        await self.simulate_call_service("homeassistant", "start", timeout=timeout)

    async def simulate_homeassistant_stop(
        self,
        timeout: float = 2.0,
    ) -> None:
        """Convenience: simulate a homeassistant stop call_service event.

        Delegates to :meth:`simulate_call_service`.
        """
        await self.simulate_call_service("homeassistant", "stop", timeout=timeout)

    async def _drain_task_bucket(self, *, timeout: float = 2.0) -> None:
        """Wait until bus dispatch queue AND app task_bucket are jointly quiescent.

        Iterates: wait for bus dispatch idle, wait for task_bucket pending tasks, re-check.
        Exits only when both are quiescent after a yield cycle. Covers arbitrary-depth
        task chains (A→B→C) and surfaces any handler exceptions via DrainError.

        Exceptions are collected via an exception recorder installed on ``app.task_bucket``
        for the duration of the drain. The recorder fires from the task's done callback,
        which guarantees that fast-completing tasks (those that finish between successive
        ``pending_tasks()`` snapshots) are still captured — closing the snapshot-timing
        window that the ``asyncio.wait`` iteration pattern cannot cover.

        Args:
            timeout: Maximum seconds to wait.

        Raises:
            DrainError: If any handler task raised a non-cancellation exception.
                When a timeout also occurs, this is the primary exception
                raised, chained from a ``DrainTimeout`` so the handler crash
                is visible as the root failure.
            DrainTimeout: If the drain does not reach quiescence within
                ``timeout`` and no handler exceptions were collected.

        Both ``DrainError`` and ``DrainTimeout`` inherit from ``DrainFailure``,
        so callers can catch either outcome uniformly with
        ``except DrainFailure:``.

        Note:
            Only ``app.task_bucket`` is drained. Tasks spawned by Bus-owned callbacks
            (including debounce and throttle handlers registered directly at the Bus
            level, outside an App context) land in ``bus.task_bucket`` and are NOT
            visible to this drain. For full-fidelity draining, route listeners
            through App-level registration via ``self.bus.on_state_change`` inside
            an App.
        """
        harness = self._require_harness()

        bus_service = harness.hassette._bus_service
        assert bus_service is not None, (
            "BusService unexpectedly None at drain time — harness setup may have partially failed"
        )

        app = self._app
        deadline = asyncio.get_running_loop().time() + timeout
        collected_exceptions: list[tuple[str, BaseException]] = []

        # Install an exception recorder on app.task_bucket for the duration of the drain.
        # This captures exceptions from tasks that complete at any point during the drain,
        # including fast-completing tasks that finish between pending_tasks() snapshots.
        # The seen_tasks guard prevents double-counting if a task's done callbacks fire
        # in an order that would otherwise expose the same exception twice.
        seen_tasks: set[asyncio.Task] = set()

        def _recorder(task: asyncio.Task, exc: BaseException) -> None:
            if task in seen_tasks:
                return
            seen_tasks.add(task)
            collected_exceptions.append((task.get_name(), exc))

        if app is not None:
            app.task_bucket.install_exception_recorder(_recorder)

        try:
            while True:
                # Top-of-loop deadline guard: prevents infinite spin on perpetually-spawning handlers
                if asyncio.get_running_loop().time() >= deadline:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)

                # Step 1: wait for bus dispatch queue to clear. Wrap await_dispatch_idle
                # to translate its TimeoutError into our diagnostic.
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)
                try:
                    await bus_service.await_dispatch_idle(timeout=remaining)
                except TimeoutError:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)

                # Step 2: wait for any pending tasks in the app's task_bucket.
                # Exceptions are collected via the recorder installed above — no per-task
                # collection needed here. We still await the tasks to pace the loop.
                if app is not None:
                    pending = app.task_bucket.pending_tasks()
                    if pending:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)
                        _done, still_pending = await asyncio.wait(pending, timeout=remaining)
                        if still_pending:
                            self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)

                # Step 3: stability check via await_dispatch_idle, which has its own 5ms anyio
                # stability window. No-op when dispatch is already idle; re-runs the stability
                # check if new events arrived during step 2. Re-check the deadline first —
                # passing timeout=0 collapses the 5ms anyio window to nothing, defeating the
                # whole point of using await_dispatch_idle here.
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)
                try:
                    await bus_service.await_dispatch_idle(timeout=remaining)
                except TimeoutError:
                    self._raise_drain_timeout(timeout, bus_service, app, collected_exceptions)

                # Step 4: exit condition — both sides quiescent.
                if app is None or not app.task_bucket.pending_tasks():
                    if bus_service.is_dispatch_idle:
                        # All quiescent; surface any collected exceptions.
                        if collected_exceptions:
                            raise DrainError(collected_exceptions)
                        return
                # else: loop back for another pass
        finally:
            if app is not None:
                app.task_bucket.uninstall_exception_recorder()

    def _raise_drain_timeout(
        self,
        timeout: float,
        bus_service: "BusService",
        app: "App | None",
        collected_exceptions: "list[tuple[str, BaseException]]",
    ) -> None:
        """Build and raise a diagnostic DrainTimeout with pending task names and debounce hint.

        When exceptions have already been collected, raises ``DrainError`` chained from
        the ``DrainTimeout`` so the handler crash is visible as the primary failure.

        Args:
            timeout: The drain timeout that elapsed.
            bus_service: The BusService instance to query for dispatch state.
            app: The app whose task_bucket to query (may be None).
            collected_exceptions: Exceptions gathered by the recorder so far.

        Raises:
            DrainError: When ``collected_exceptions`` is non-empty (chained from DrainTimeout).
            DrainTimeout: When no exceptions were collected.
        """
        task_names: list[str] = []
        if app is not None:
            task_names = [t.get_name() for t in app.task_bucket.pending_tasks()]

        base = (
            f"AppTestHarness drain did not reach quiescence within {timeout}s "
            f"(bus dispatch pending: {bus_service.dispatch_pending_count}, "
            f"task_bucket pending: {len(task_names)})"
        )
        if task_names:
            base += f"; pending task names: {task_names}"
        if any("debounce" in n for n in task_names):
            base += (
                " — if tasks include 'handler:debounce', your drain timeout may be shorter "
                "than the handler's debounce window. Pass `timeout=` larger than your largest "
                "debounce delay."
            )
        if collected_exceptions:
            drain_err = DrainError(collected_exceptions)
            timeout_err = DrainTimeout(base)
            raise drain_err from timeout_err
        raise DrainTimeout(base)
