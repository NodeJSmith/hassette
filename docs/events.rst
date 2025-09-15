Events
======

Subscribe to state changes and services using the Bus.

Examples
--------
.. code-block:: python

   self.bus.on_entity("binary_sensor.motion", handler=self.on_motion, changed_to="on")
   self.bus.on_attribute("mobile_device.me", "battery_level", handler=self.on_batt)
   self.bus.on_call_service(domain="light", service="turn_on", handler=self.on_turn_on)
