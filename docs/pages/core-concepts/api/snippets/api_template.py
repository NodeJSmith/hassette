from hassette import App


class TemplateApp(App):
    async def on_initialize(self):
        # Simple render
        result = await self.api.render_template("{{ states('sun.sun') }}")
        self.logger.info("Sun state: %s", result)

        # Complex server-side logic
        template = (
            "{{ states.sensor"
            " | selectattr('attributes.device_class',"
            " 'eq', 'temperature')"
            " | map(attribute='state')"
            " | map('float', default=0)"
            " | average }}"
        )
        avg_temp = await self.api.render_template(template)
        self.logger.info("Average temp: %s", avg_temp)
