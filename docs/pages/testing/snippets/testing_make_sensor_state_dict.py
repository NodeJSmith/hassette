from hassette.test_utils import make_sensor_state_dict

state = make_sensor_state_dict(
    entity_id="sensor.temperature",
    state="21.5",
    unit_of_measurement="°C",
    device_class="temperature",
)
