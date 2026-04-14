from appdaemon.plugins.hass import Hass


class MyApp(Hass):
    def initialize(self):
        self.log(f"{self.args=}")
        entity = self.args["args"]["entity"]
        brightness = self.args["args"]["brightness"]
        self.log(f"My configured entity is {entity!r} (type {type(entity)})")
        self.log(f"My configured brightness is {brightness!r} (type {type(brightness)})")

        # 2025-10-13 18:59:04.820599 INFO my_app: self.args={'name': 'my_app', 'config_path': PosixPath('./apps.yaml'), 'module': 'my_app', 'class': 'MyApp', 'args': {'entity': 'light.kitchen', 'brightness': 200}}
        # 2025-10-13 18:40:23.676650 INFO my_app: My configured entity is 'light.kitchen' (type <class 'str'>)
        # 2025-10-13 18:40:23.677422 INFO my_app: My configured brightness is 200 (type <class 'int'>)
