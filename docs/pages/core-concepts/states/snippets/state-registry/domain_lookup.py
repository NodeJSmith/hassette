from hassette import STATE_REGISTRY

# Get class for a domain
state_class = STATE_REGISTRY.resolve(domain="light")
# Returns: LightState
