"""Puerto de lectura del contenido de las plantillas declaradas por vendor."""

from typing import Protocol


class TemplateSource(Protocol):
    """Permite consultar plantillas sin acoplar la aplicación a su almacenamiento."""

    def read_text(self, vendor_id: str, resource_path: str) -> str:
        """Devuelve el contenido de la plantilla identificada por vendor y ruta relativa."""
        ...
