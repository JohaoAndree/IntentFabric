"""Verifica el despacho extensible y los errores del registro de parsers."""

from collections.abc import Mapping
from typing import Any

import pytest

from intentfabric.application.intent_parsing import IntentParserRegistry
from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import ServiceIntent


class _Parser:
    """Simula un parser de servicio para verificar el registro."""

    def __init__(self, service_type: str) -> None:
        self.service_type = service_type

    def parse(self, raw: Mapping[str, Any]) -> ServiceIntent:
        """Conserva la descripción para comprobar el despacho de un servicio nuevo."""
        return ServiceIntent(description=raw["description"])


def test_registry_dispatches_to_registered_parser() -> None:
    """Permite interpretar un servicio nuevo mediante registro sin modificar el núcleo."""
    registry = IntentParserRegistry()
    registry.register(_Parser("LAB"))
    raw = {"service_type": "LAB", "description": "LAB#INTE#0001"}
    assert registry.parse(raw) == ServiceIntent("LAB#INTE#0001")


def test_unknown_service_lists_registered_types_in_stable_order() -> None:
    """Enumera los servicios registrados con un orden independiente del registro."""
    messages = []
    for order in [("L3VPN", "DIA"), ("DIA", "L3VPN")]:
        registry = IntentParserRegistry()
        for service_type in order:
            registry.register(_Parser(service_type))
        with pytest.raises(IntentParseError) as error:
            registry.parse({"service_type": "UNKNOWN"})
        messages.append(str(error.value))
    assert messages == [
        "service_type: servicio desconocido 'UNKNOWN'; registrados: DIA, L3VPN"
    ] * 2


@pytest.mark.parametrize(
    ("raw", "message"),
    [({}, "service_type: campo faltante"),
     ({"service_type": []}, "service_type: se requiere texto"),
     ([], "$: se requiere un objeto"),
     ({"service_type": "DIA"},
      "service_type: servicio desconocido 'DIA'; registrados: ninguno")],
)
def test_registry_rejects_invalid_dispatch_input(raw: Any, message: str) -> None:
    """Rechaza entradas sin un servicio registrado con un diagnóstico de campo."""
    with pytest.raises(IntentParseError) as error:
        IntentParserRegistry().parse(raw)
    assert str(error.value) == message


def test_registry_instances_do_not_share_state() -> None:
    """Mantiene los parsers registrados aislados entre instancias."""
    first = IntentParserRegistry()
    first.register(_Parser("DIA"))
    with pytest.raises(IntentParseError, match="registrados: ninguno"):
        IntentParserRegistry().parse({"service_type": "DIA"})
