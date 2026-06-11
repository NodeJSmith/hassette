def initialize(self):
    self.listen_state(self.on_motion, "binary_sensor.motion", new="on")

def on_motion(self, entity, attribute, old, new, **kwargs):
    self.log(f"Motion detected on {entity}")
