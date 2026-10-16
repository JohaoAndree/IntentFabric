"""Comprueba la composición del registro DIA y sus vendors conocidos."""

from types import ModuleType
from typing import Any

import pytest

from intentfabric import bootstrap
from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import DiaIntent
from intentfabric.domain.vendor_definition import VendorDefinition
from intentfabric.vendors import cisco


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
    intent = bootstrap.build_plugin_catalog().parse_intent(_raw())
    assert isinstance(intent, DiaIntent)
    assert intent.access.vendor == "huawei"
    assert intent.provider_edge.vendor == "cisco"


def test_bootstrap_accepts_new_vendor_without_core_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Admite otro vendor al proporcionarlo a la raíz de composición."""
    package = ModuleType("lab_vendor")
    package.VENDOR_DEFINITION = VendorDefinition("lab", {})
    monkeypatch.setattr(bootstrap, "VENDOR_PACKAGES", (package, cisco))
    catalog = bootstrap.build_plugin_catalog()
    assert catalog.parse_intent(_raw("lab")).access.vendor == "lab"
    with pytest.raises(IntentParseError, match=r"path\[0\].vendor: vendor no registrado"):
        catalog.parse_intent(_raw())


def test_bootstrap_does_not_share_custom_vendors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla los vendors personalizados de los registros construidos después."""
    package = ModuleType("lab_vendor")
    package.VENDOR_DEFINITION = VendorDefinition("lab", {})
    with monkeypatch.context() as context:
        context.setattr(bootstrap, "VENDOR_PACKAGES", (package,))
        assert bootstrap.build_plugin_catalog().vendor_ids() == frozenset({"lab"})
    assert bootstrap.build_plugin_catalog().parse_intent(_raw()).access.vendor == "huawei"


def test_bootstrap_keeps_unknown_service_diagnostic() -> None:
    """Informa DIA como registrado cuando se solicita un servicio desconocido."""
    with pytest.raises(IntentParseError) as error:
        bootstrap.build_plugin_catalog().parse_intent({"service_type": "OTHER"})
    assert str(error.value) == "service_type: servicio desconocido 'OTHER'; registrados: DIA"
