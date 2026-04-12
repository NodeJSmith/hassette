from hassette.test_utils import create_state_change_event

event = create_state_change_event(
    entity_id="binary_sensor.motion",
    old_value="off",
    new_value="on",
    old_attrs={"device_class": "motion"},
    new_attrs={"device_class": "motion"},
)
