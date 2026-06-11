def initialize(self):
    self.listen_event(
        self.on_service,
        "call_service",
        domain="light",
        service="turn_on",
    )
