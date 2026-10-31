from hassette.models import states
from hassette.testing import make_light_state_dict, make_typed_state

state = make_typed_state(
    states.LightState,
    make_light_state_dict("light.kitchen", "on", brightness=200),
)
