from hassette import App


class TemplateVariablesApp(App):
    async def on_initialize(self):
        template = "{{ entity }} is {{ states(entity) }}"
        for entity_id in ("sun.sun", "light.kitchen"):
            result = await self.api.render_template(template, variables={"entity": entity_id})
            self.logger.info("%s", result)
