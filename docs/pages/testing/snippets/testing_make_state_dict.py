from hassette.test_utils import make_state_dict

state = make_state_dict(
    "sensor.temperature",
    "21.5",
    attributes={"unit_of_measurement": "°C", "device_class": "temperature"},
)
