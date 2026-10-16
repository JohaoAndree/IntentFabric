"""Definiciones inmutables de vendors y sus recursos de plantilla."""

from collections.abc import Mapping
from dataclasses import dataclass
import re
from types import MappingProxyType

from intentfabric.domain.template_key import TemplateKey


@dataclass(frozen=True)
class VendorDefinition:
    """Declara un vendor y conserva una copia inmutable de sus rutas de plantilla."""

    vendor_id: str
    templates: Mapping[TemplateKey, str]

    def __post_init__(self) -> None:
        if not isinstance(self.vendor_id, str) or re.fullmatch(
            r"[a-z][a-z0-9_]{1,31}", self.vendor_id
        ) is None:
            raise ValueError("vendor_id: se requiere el formato ^[a-z][a-z0-9_]{1,31}$")
        templates = dict(self.templates)
        for resource_path in templates.values():
            if (
                not isinstance(resource_path, str)
                or not resource_path
                or resource_path.startswith("/")
                or "\\" in resource_path
                or ".." in resource_path.split("/")
                or not resource_path.endswith(".j2")
            ):
                raise ValueError(
                    "templates: se requiere una ruta relativa .j2 sin barra inicial, "
                    "barra inversa ni segmento '..'"
                )
        object.__setattr__(self, "templates", MappingProxyType(templates))
