from hassette.test_utils import make_light_state_dict

state = make_light_state_dict(
    entity_id="light.kitchen",
    state="on",
    brightness=200,
    color_temp=370,
)
