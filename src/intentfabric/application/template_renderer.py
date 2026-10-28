"""Puerto de renderizado estricto de plantillas por vendor."""

from collections.abc import Mapping
from typing import Protocol

from intentfabric.domain.template_key import TemplateKey


class TemplateRendererPort(Protocol):
    """Define la generacion de texto sin acoplar la aplicacion al motor."""

    def render(self, vendor_id: str, key: TemplateKey, context: Mapping[str, object]) -> str:
        """Renderiza la plantilla del vendor con el contexto proporcionado."""
        ...
