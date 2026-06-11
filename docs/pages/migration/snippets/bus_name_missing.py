# Raises ListenerNameRequiredError immediately
await self.bus.on_state_change("light.kitchen", handler=self.on_change)
