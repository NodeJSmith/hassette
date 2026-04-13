from hassette import App


class NoteChangedConditionApp(App):
    async def on_initialize(self):
        # --8<-- [start:note_changed]
        # `old` and `new` are the raw state strings (e.g. "on", "off", "unknown").
        # This example only fires when the state was previously known and actually changed.
        self.bus.on_state_change(
            entity_id="light.office",
            handler=self.on_light_change,
            changed=lambda old, new: old is not None and new is not None and old != new,
        )
        # --8<-- [end:note_changed]

    async def on_light_change(self):
        pass
