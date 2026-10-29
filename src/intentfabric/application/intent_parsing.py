"""Puerto y registro de parsers de intención por tipo de servicio."""

from collections.abc import Mapping
from typing import Any, Protocol

from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import ServiceIntent


class ServiceIntentParser(Protocol):
    """Define la interpretación de una intención de un tipo de servicio."""

    service_type: str

    def parse(self, raw: Mapping[str, Any]) -> ServiceIntent:
        """Convierte datos estructurados o lanza IntentParseError con la ruta inválida."""
        ...


class IntentParserRegistry:
    """Despacha intenciones a los parsers registrados por tipo de servicio."""

    def __init__(self) -> None:
        self._parsers: dict[str, ServiceIntentParser] = {}

    def register(self, parser: ServiceIntentParser) -> None:
        """Asocia un parser a su tipo de servicio."""
        self._parsers[parser.service_type] = parser

    def parse(self, raw: Mapping[str, Any]) -> ServiceIntent:
        """Despacha por service_type; los desconocidos enumeran los tipos registrados."""
        if not isinstance(raw, Mapping):
            raise IntentParseError("$: se requiere un objeto")
        if "service_type" not in raw:
            raise IntentParseError("service_type: campo faltante")
        service_type = raw["service_type"]
        if not isinstance(service_type, str):
            raise IntentParseError("service_type: se requiere texto")
        normalized = service_type.strip().upper()
        if normalized in self._parsers or normalized == "DIA":
            service_type = normalized
        if service_type not in self._parsers:
            registered = ", ".join(sorted(self._parsers)) or "ninguno"
            raise IntentParseError(
                f"service_type: servicio desconocido {service_type!r}; "
                f"registrados: {registered}"
            )
        return self._parsers[service_type].parse(raw)
