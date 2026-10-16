"""Comprueba los contratos inmutables de los modelos de intención."""

from dataclasses import FrozenInstanceError, fields
from ipaddress import IPv4Address, IPv4Network

import pytest

from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import (
    AccessHop, DiaIntent, ProviderEdgeHop, ServiceIntent, TransitHop,
)


def _intent() -> DiaIntent:
    return DiaIntent(
        description="LAB#INTE#0001", vlan_id=3001, vrf_name="LAB-INTERNET",
        wan_network=IPv4Network("10.255.0.0/30"),
        lan_network=IPv4Network("203.0.113.0/29"), bandwidth_mbps=50,
        qos_policy_name="LAB_50MB_PARENT",
        access=AccessHop("huawei", IPv4Address("192.0.2.11"), "port", "uplink"),
        transits=(TransitHop("cisco", IPv4Address("192.0.2.12"), "down", "up"),),
        provider_edge=ProviderEdgeHop("huawei", IPv4Address("192.0.2.21"), "parent"),
    )


def test_intent_preserves_typed_data_and_service_constant() -> None:
    """Conserva la ruta ordenada y el tipo de servicio como constante de clase."""
    intent = _intent()
    assert isinstance(intent, ServiceIntent)
    assert intent == _intent()
    assert intent.service_type == DiaIntent.service_type == "DIA"
    assert "service_type" not in {field.name for field in fields(intent)}
    assert intent.wan_network == IPv4Network("10.255.0.0/30")
    assert intent.access.management_ip == IPv4Address("192.0.2.11")
    assert isinstance(intent.transits, tuple)
    assert intent.transits[0].vendor == "cisco"


@pytest.mark.parametrize("part", ["intent", "access", "transit", "provider_edge"])
def test_intent_and_hops_are_frozen(part: str) -> None:
    """Impide reasignar campos de la intención y de cada tipo de salto."""
    intent = _intent()
    model = {
        "intent": intent, "access": intent.access, "transit": intent.transits[0],
        "provider_edge": intent.provider_edge,
    }[part]
    field = fields(model)[0].name
    with pytest.raises(FrozenInstanceError):
        setattr(model, field, "changed")


def test_parse_error_preserves_field_path() -> None:
    """Conserva la ruta del campo en el diagnóstico de parsing."""
    assert str(IntentParseError("path[1].vendor: vendor desconocido")) == (
        "path[1].vendor: vendor desconocido"
    )
