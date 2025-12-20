from hassette.core.state_registry import convert_state_dict_to_model
from hassette.models import states

state_dict = {}  # ...

# Convert with explicit target type
state = convert_state_dict_to_model(state_dict, states.LightState)

# Convert with Union type
state = convert_state_dict_to_model(state_dict, states.LightState | states.SwitchState)
