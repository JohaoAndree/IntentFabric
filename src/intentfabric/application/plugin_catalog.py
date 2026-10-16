"""Catálogo de vendors, servicios y combinaciones de plantilla soportadas."""

from collections.abc import Mapping
from typing import Any

from intentfabric.application.intent_parsing import IntentParserRegistry, ServiceIntentParser
from intentfabric.application.template_source import TemplateSource
from intentfabric.domain.errors import (
    PluginConsistencyError, PluginRegistrationError, TemplateNotFoundError,
    UnsupportedCombinationError,
)
from intentfabric.domain.intent import ServiceIntent
from intentfabric.domain.template_key import TemplateKey
from intentfabric.domain.vendor_definition import VendorDefinition


class PluginCatalog:
    """Registra capacidades declaradas y verifica sus recursos antes de utilizarlos."""

    def __init__(self) -> None:
        self._vendors: dict[str, VendorDefinition] = {}
        self._service_types: set[str] = set()
        self._intent_parsers = IntentParserRegistry()

    def register_vendor(self, definition: VendorDefinition) -> None:
        """Registra una definición de vendor y rechaza identificadores duplicados."""
        if definition.vendor_id in self._vendors:
            raise PluginRegistrationError(f"vendor_id: registro duplicado {definition.vendor_id!r}")
        self._vendors[definition.vendor_id] = definition

    def register_service(self, parser: ServiceIntentParser) -> None:
        """Registra el parser de un servicio y rechaza tipos duplicados."""
        if parser.service_type in self._service_types:
            raise PluginRegistrationError(f"service_type: registro duplicado {parser.service_type!r}")
        self._intent_parsers.register(parser)
        self._service_types.add(parser.service_type)

    def vendor_ids(self) -> frozenset[str]:
        """Devuelve una instantánea inmutable de los vendors registrados."""
        return frozenset(self._vendors)

    def service_types(self) -> frozenset[str]:
        """Devuelve una instantánea inmutable de los servicios registrados."""
        return frozenset(self._service_types)

    def supports(self, vendor_id: str, key: TemplateKey) -> bool:
        """Indica si el vendor registrado declara la clave de plantilla solicitada."""
        definition = self._vendors.get(vendor_id)
        return definition is not None and key in definition.templates

    def resolve_template(self, vendor_id: str, key: TemplateKey) -> str:
        """Resuelve la ruta declarada o lanza UnsupportedCombinationError."""
        if not self.supports(vendor_id, key):
            raise UnsupportedCombinationError(
                f"{_combination_label(vendor_id, key)}: combinación no soportada"
            )
        return self._vendors[vendor_id].templates[key]

    def parse_intent(self, raw: Mapping[str, Any]) -> ServiceIntent:
        """Delega la interpretación de la intención al registro de parsers."""
        return self._intent_parsers.parse(raw)

    def verify_consistency(self, source: TemplateSource) -> tuple[str, ...]:
        """Devuelve errores ordenados de servicios ausentes y recursos ilegibles o vacíos."""
        messages: list[str] = []
        for vendor_id, definition in self._vendors.items():
            for key, resource_path in definition.templates.items():
                label = _combination_label(vendor_id, key)
                if key.service_type not in self._service_types:
                    messages.append(f"{label}: servicio no registrado")
                try:
                    text = source.read_text(vendor_id, resource_path)
                except (TemplateNotFoundError, OSError, UnicodeError):
                    messages.append(f"{label}: plantilla ilegible {resource_path!r}")
                else:
                    if not text.strip():
                        messages.append(f"{label}: plantilla vacía {resource_path!r}")
        return tuple(sorted(messages))

    def assert_consistent(self, source: TemplateSource) -> None:
        """Lanza PluginConsistencyError con todos los errores de consistencia unidos."""
        messages = self.verify_consistency(source)
        if messages:
            raise PluginConsistencyError("\n".join(messages))


def _combination_label(vendor_id: str, key: TemplateKey) -> str:
    return f"{vendor_id}/{key.service_type}/{key.operation}/{key.role}/{key.variant}"
