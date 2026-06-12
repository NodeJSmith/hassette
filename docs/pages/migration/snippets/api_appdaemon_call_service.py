def my_callback(self, **kwargs):
    self.call_service("light/turn_on", entity_id="light.kitchen", brightness=200)

    # or use the helper
    self.turn_on("light.kitchen", brightness=200)
