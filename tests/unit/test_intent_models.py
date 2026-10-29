"""Comprueba los contratos inmutables de los modelos de intención."""

from dataclasses import FrozenInstanceError, fields, replace
from ipaddress import IPv4Address, IPv4Network

import pytest

from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import (
    AccessHop, DiaIntent, ProviderEdgeHop, ServiceIntent, TransitHop,
)
from intentfabric.domain.template_key import NodeRole


def _intent() -> DiaIntent:
    return DiaIntent(
        description="LAB#INTE#0001", vlan_id=3001, vrf_name="LAB-INTERNET",
        wan_network=IPv4Network("10.255.0.0/30"),
        lan_network=IPv4Network("203.0.113.0/29"), bandwidth_mbps=50,
        qos_policy_name="LAB_50MB_PARENT",
        access=AccessHop("LAB-ACCESS", "huawei", IPv4Address("192.0.2.11"), "GigabitEthernet0/0/1", "GigabitEthernet0/0/24"),
        transits=(TransitHop("LAB-TRANSIT", "cisco", IPv4Address("192.0.2.12"), "GigabitEthernet1/0/23", "GigabitEthernet1/0/24"),),
        provider_edge=ProviderEdgeHop("LAB-PE", "huawei", IPv4Address("192.0.2.21"), "GigabitEthernet0/0/1"),
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


def test_navigation_preserves_canonical_path_and_roles() -> None:
    """Expone acceso, transitos y PE sin agregar campos ni alterar el orden."""
    intent = _intent()
    assert intent.hops == (intent.access, *intent.transits, intent.provider_edge)
    assert tuple(hop.role for hop in intent.hops) == (
        NodeRole.ACCESS, NodeRole.TRANSIT, NodeRole.PROVIDER_EDGE,
    )
    assert "hops" not in {field.name for field in fields(intent)}
    for hop in intent.hops:
        assert "role" not in {field.name for field in fields(hop)}


@pytest.mark.parametrize("node_id", ("", " ", None, 1))
@pytest.mark.parametrize("position", ("access", "transit", "provider_edge"))
def test_hops_require_nonempty_logical_identity(node_id: object, position: str) -> None:
    """Exige node_id textual no vacio para los tres tipos de salto."""
    intent = _intent()
    hop = {"access": intent.access, "transit": intent.transits[0], "provider_edge": intent.provider_edge}[position]
    with pytest.raises(ValueError, match="^node_id:"):
        replace(hop, node_id=node_id)


def test_hops_normalize_all_interface_fields_and_wrap_invalid_names() -> None:
    """Normaliza cada atributo de interfaz y convierte errores al contrato ValueError."""
    access = AccessHop("access", "cisco", IPv4Address("192.0.2.1"), "Gi0/1", "GE0/2")
    transit = TransitHop("transit", "huawei", IPv4Address("192.0.2.2"), "GE0/1", "Gi0/2")
    pe = ProviderEdgeHop("pe", "huawei", IPv4Address("192.0.2.3"), "GE0/1.10")
    assert (access.customer_port, access.uplink_interface) == ("GigabitEthernet0/1", "GigabitEthernet0/2")
    assert (transit.downstream_interface, transit.upstream_interface) == ("GigabitEthernet0/1", "GigabitEthernet0/2")
    assert pe.parent_interface == "GigabitEthernet0/1.10"
    for hop, attributes in ((access, ("customer_port", "uplink_interface")),
                            (transit, ("downstream_interface", "upstream_interface")),
                            (pe, ("parent_interface",))):
        for attribute in attributes:
            with pytest.raises(ValueError, match="interface") as error:
                replace(hop, **{attribute: "invalid"})
            assert error.value.__cause__ is not None
