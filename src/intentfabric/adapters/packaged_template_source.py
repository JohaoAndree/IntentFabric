"""Lectura UTF-8 de plantillas desde las raíces de recursos de cada vendor."""

from collections.abc import Mapping
from importlib.resources.abc import Traversable

from intentfabric.domain.errors import TemplateNotFoundError


class PackagedTemplateSource:
    """Accede a los recursos de plantilla sin depender de rutas del sistema anfitrión."""

    def __init__(self, roots: Mapping[str, Traversable]) -> None:
        self._roots = dict(roots)

    def read_text(self, vendor_id: str, resource_path: str) -> str:
        """Lee una ruta declarada en UTF-8; raíz o archivo ausentes causan TemplateNotFoundError."""
        if vendor_id not in self._roots:
            raise TemplateNotFoundError(f"{vendor_id}: raíz de recursos no registrada")
        resource = self._roots[vendor_id]
        try:
            for segment in resource_path.split("/"):
                resource = resource.joinpath(segment)
            if not resource.is_file():
                raise TemplateNotFoundError(f"{vendor_id}: plantilla inexistente {resource_path!r}")
            with resource.open("r", encoding="utf-8", newline="\n") as stream:
                return stream.read()
        except FileNotFoundError as error:
            raise TemplateNotFoundError(
                f"{vendor_id}: plantilla inexistente {resource_path!r}"
            ) from error
