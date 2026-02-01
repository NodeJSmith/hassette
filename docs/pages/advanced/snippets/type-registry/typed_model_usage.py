from hassette import states

# Raw state data from Home Assistant
raw_data = {
    "entity_id": "sensor.temperature",
    "state": "23.5",  # String from HA
    "attributes": {"unit_of_measurement": "°C"},
    "context": {"id": "12345", "user_id": "user_1"},
}

# Creating a typed state model automatically converts the value
sensor_state = states.SensorState(**raw_data)
print(type(sensor_state.value))  # <class 'float'> - automatically converted!
