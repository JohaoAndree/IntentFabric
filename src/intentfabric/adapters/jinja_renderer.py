"""Renderizado Jinja2 estricto y normalizado de recursos declarados."""

from collections.abc import Mapping

import jinja2

from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.application.template_source import TemplateSource
from intentfabric.domain.errors import TemplateRenderError
from intentfabric.domain.generation import normalize_rendered_config
from intentfabric.domain.template_key import TemplateKey


class JinjaTemplateRenderer:
    """Resuelve plantillas empaquetadas y falla ante variables o sintaxis invalidas."""

    def __init__(self, catalog: PluginCatalog, template_source: TemplateSource) -> None:
        self._catalog = catalog
        self._template_source = template_source
        self._environment = jinja2.Environment(
            undefined=jinja2.StrictUndefined, autoescape=False,
            trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
            newline_sequence="\n",
        )

    def render(self, vendor_id: str, key: TemplateKey, context: Mapping[str, object]) -> str:
        """Devuelve configuracion normalizada o expone la causa del fallo Jinja2."""
        resource_path = self._catalog.resolve_template(vendor_id, key)
        raw_template = self._template_source.read_text(vendor_id, resource_path)
        try:
            rendered_text = self._environment.from_string(raw_template).render(dict(context))
        except jinja2.TemplateError as error:
            raise TemplateRenderError(key, str(error)) from error
        return normalize_rendered_config(rendered_text)
