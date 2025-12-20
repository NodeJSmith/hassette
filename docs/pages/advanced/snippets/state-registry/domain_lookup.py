from hassette.context import get_state_registry

registry = get_state_registry()

# Get class for a domain
state_class = registry.resolve(domain="light")
# Returns: LightState
