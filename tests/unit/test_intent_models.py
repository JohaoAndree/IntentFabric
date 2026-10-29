"""Comprueba los contratos inmutables de los modelos de intención."""

from dataclasses import FrozenInstanceError, fields, replace
from ipaddress import IPv4Address, IPv4Network

import pytest

from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import (
    AccessHop, DiaIntent, L2VpnIntent, L3VpnIntent, ProviderEdgeHop, ServiceIntent, TransitHop,
    is_valid_asn, is_valid_evi_id, is_valid_pseudowire_id, is_valid_route_distinguisher_or_target,
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


def test_l3vpn_preserves_frozen_path_and_allows_semantic_defects() -> None:
    """Conserva contratos DIA y permite defectos para validacion acumulativa."""
    dia = _intent()
    intent = L3VpnIntent(
        description=dia.description, vlan_id=0, vrf_name=dia.vrf_name,
        wan_network=dia.wan_network, bandwidth_mbps=dia.bandwidth_mbps,
        qos_policy_name=dia.qos_policy_name, rd="invalid", rt_import="invalid",
        rt_export="invalid", pe_asn=65000, ce_asn=65000,
        access=dia.access, transits=dia.transits, provider_edge=dia.provider_edge,
    )
    assert isinstance(intent, ServiceIntent)
    assert intent.service_type == L3VpnIntent.service_type == "L3VPN"
    assert intent.hops == dia.hops
    assert intent.qos_policy == dia.qos_policy_name
    assert intent.lan_network is None
    assert {"service_type", "hops", "qos_policy"}.isdisjoint(field.name for field in fields(intent))
    with pytest.raises(FrozenInstanceError):
        intent.rd = "65000:1"
    with pytest.raises(FrozenInstanceError):
        intent.hops = ()
    assert replace(intent, lan_network=dia.lan_network).lan_network == dia.lan_network


@pytest.mark.parametrize("value", (1, 65535, 65536, 4294967294))
def test_asn_accepts_complete_supported_range(value: int) -> None:
    """Acepta los limites y la transicion entre ASN de dos y cuatro octetos."""
    assert is_valid_asn(value)


@pytest.mark.parametrize("value", (0, -1, 4294967295, True, False, 65000.0, "65000", None))
def test_asn_rejects_reserved_values_and_nonintegers(value: object) -> None:
    """Rechaza valores reservados, booleanos y tipos no enteros."""
    assert not is_valid_asn(value)


@pytest.mark.parametrize("value", (
    "1:0", "65535:4294967295", "65536:65535", "4294967295:0",
    "192.0.2.1:65535", "0.0.0.0:0", "255.255.255.255:0",
))
def test_rd_rt_accepts_all_three_encodings(value: str) -> None:
    """Acepta los limites de los tres formatos admin:assigned."""
    assert is_valid_route_distinguisher_or_target(value)


@pytest.mark.parametrize("value", (
    "0:1", "65535:4294967296", "65536:65536", "4294967296:0",
    "192.0.2.1:65536", "256.0.0.1:0", "192.000.2.1:0", "01:1", "1:01",
    "1:-1", "+1:1", "1:+1", "1:1:1", "1", "", " 1:1", "1:1 ",
    "1:1\n", "1: 1", "1\t:1", "１:1", "1:١", None, 65000, "1:" + "9" * 5000,
))
def test_rd_rt_rejects_ambiguous_and_out_of_range_values(value: object) -> None:
    """Rechaza formatos ambiguos, whitespace, digitos no ASCII y desbordamientos."""
    assert not is_valid_route_distinguisher_or_target(value)


def test_l2vpn_preserves_frozen_path_and_allows_semantic_defects() -> None:
    """Conserva ruta y alias inmutables permitiendo defectos semanticos."""
    dia = _intent()
    intent = L2VpnIntent(
        description=dia.description, vlan_id=0, bandwidth_mbps=2000,
        qos_policy_name=dia.qos_policy_name, pw_id=0, evi_id=310,
        local_ac_id=0, remote_ac_id=0, rd="invalid", rt_import="invalid",
        rt_export="invalid", remote_pe_node_id="REMOTE-PE",
        remote_pe_ip=IPv4Address("192.0.2.22"), access=dia.access,
        transits=dia.transits, provider_edge=dia.provider_edge,
    )
    assert isinstance(intent, ServiceIntent)
    assert intent.service_type == L2VpnIntent.service_type == "L2VPN"
    assert intent.hops == dia.hops
    assert intent.qos_policy == dia.qos_policy_name
    assert intent.instance_name == "VPWS_310"
    assert replace(intent, evi_id=410).instance_name == "VPWS_410"
    assert {"service_type", "hops", "qos_policy", "instance_name"}.isdisjoint(
        field.name for field in fields(intent)
    )
    for attribute in ("pw_id", "hops", "qos_policy", "instance_name"):
        with pytest.raises(FrozenInstanceError):
            setattr(intent, attribute, "changed")


@pytest.mark.parametrize("value", (1, 65535, 65536, 4294967295))
def test_pseudowire_id_accepts_unsigned_32_bit_range(value: int) -> None:
    """Acepta los limites de VC-ID y AC-ID sin reservar el maximo."""
    assert is_valid_pseudowire_id(value)


@pytest.mark.parametrize("value", (0, -1, 4294967296, True, False, 1.0, "1", None))
def test_pseudowire_id_rejects_zero_overflow_and_nonintegers(value: object) -> None:
    """Rechaza cero, desbordamiento y tipos distintos del entero estricto."""
    assert not is_valid_pseudowire_id(value)


@pytest.mark.parametrize("value", (1, 65535))
def test_evi_id_accepts_unsigned_16_bit_range(value: int) -> None:
    """Acepta ambos limites del identificador EVI."""
    assert is_valid_evi_id(value)


@pytest.mark.parametrize("value", (0, -1, 65536, True, False, 1.0, "1", None))
def test_evi_id_rejects_zero_overflow_and_nonintegers(value: object) -> None:
    """Rechaza valores y tipos fuera del rango EVI estricto."""
    assert not is_valid_evi_id(value)
