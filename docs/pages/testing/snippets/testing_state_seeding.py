from hassette.test_utils import AppTestHarness

from my_apps.thermostat import ThermostatApp


async def test_thermostat_state_seeding():
    async with AppTestHarness(ThermostatApp, config={}) as harness:
        # Seed a single entity
        await harness.set_state("sensor.temperature", "20.5", unit_of_measurement="°C")

        # Seed multiple entities at once
        await harness.set_states(
            {
                "sensor.temperature": ("20.5", {"unit_of_measurement": "°C"}),
                "sensor.humidity": "55",
                "climate.living_room": "heat",
            }
        )
