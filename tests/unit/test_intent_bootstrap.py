"""Comprueba la composición del registro DIA y sus vendors conocidos."""

from typing import Any

import pytest

from intentfabric.bootstrap import build_intent_parser_registry
from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import DiaIntent


def _raw(vendor: str = "huawei") -> dict[str, Any]:
    return {
        "schema_version": "1", "service_type": "DIA", "description": "LAB#INTE#0001",
        "vlan_id": 3001, "vrf_name": "LAB-INTERNET", "wan_network": "10.255.0.0/30",
        "lan_network": "203.0.113.0/29", "bandwidth_mbps": 50,
        "qos": {"policy_name": "LAB_50MB_PARENT"},
        "path": [
            {"role": "access", "vendor": vendor, "management_ip": "192.0.2.11",
             "customer_port": "port", "uplink_interface": "uplink"},
            {"role": "pe", "vendor": "cisco", "management_ip": "192.0.2.21",
             "parent_interface": "parent"},
        ],
    }


def test_bootstrap_registers_dia_with_default_vendors() -> None:
    """Interpreta una ruta mixta con Cisco y Huawei registrados por defecto."""
    intent = build_intent_parser_registry().parse(_raw())
    assert isinstance(intent, DiaIntent)
    assert intent.access.vendor == "huawei"
    assert intent.provider_edge.vendor == "cisco"


def test_bootstrap_accepts_new_vendor_without_core_changes() -> None:
    """Admite otro vendor al proporcionarlo a la raíz de composición."""
    registry = build_intent_parser_registry(frozenset({"lab", "cisco"}))
    assert registry.parse(_raw("lab")).access.vendor == "lab"
    with pytest.raises(IntentParseError, match=r"path\[0\].vendor: vendor no registrado"):
        registry.parse(_raw())


def test_bootstrap_does_not_share_custom_vendors() -> None:
    """Aísla los vendors personalizados de los registros construidos después."""
    build_intent_parser_registry(frozenset({"lab"}))
    assert build_intent_parser_registry().parse(_raw()).access.vendor == "huawei"


def test_bootstrap_keeps_unknown_service_diagnostic() -> None:
    """Informa DIA como registrado cuando se solicita un servicio desconocido."""
    with pytest.raises(IntentParseError) as error:
        build_intent_parser_registry().parse({"service_type": "OTHER"})
    assert str(error.value) == "service_type: servicio desconocido 'OTHER'; registrados: DIA"
