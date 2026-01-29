from hassette import App


class TemplateApp(App):
    async def on_initialize(self):
        # Simple render
        result = await self.api.render_template("{{ states('sun.sun') }}")
        self.logger.info("Sun state: %s", result)

        # Complex logic
        avg_temp = await self.api.render_template("""
            {{ states.sensor | selectattr('attributes.device_class', 'eq', 'temperature')
            | map(attribute='state') | map('float', default=0) | average }}
        """)
        self.logger.info("Average temp: %s", avg_temp)
