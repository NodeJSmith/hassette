from hassette import dependencies as D
from hassette import states

# DI annotation uses StateRegistry internally
new_state: D.StateNew[states.LightState]
