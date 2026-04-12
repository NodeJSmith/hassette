self.bus.on_state_change(
    entity_id="light.office",
    handler=self.on_light_change_maybe_old,
    changed=lambda old, new: old != new,
)
