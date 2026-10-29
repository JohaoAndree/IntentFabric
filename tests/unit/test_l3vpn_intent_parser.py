"""Comprueba parsing estricto, inventario y contexto del extremo L3VPN."""

from dataclasses import replace
from ipaddress import IPv4Network

import pytest

from intentfabric.application.intent_parsing import IntentParserRegistry
from intentfabric.bootstrap import load_default_topology
from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import L3VpnIntent
from intentfabric.domain.template_key import Operation
from intentfabric.services.l3vpn import (
    L3VpnIntentParser, build_l3vpn_hop_context, create_l3vpn_intent_parser, parse_l3vpn_intent,
)


def _raw() -> dict[str, object]:
    return {
        "service_type": "L3VPN", "description": "L3VPN-CORP-000001", "vlan_id": 110,
        "wan_network": "172.16.10.0/30", "bandwidth_mbps": 100,
        "vrf_name": "VRF_CORP_A", "qos_policy": "QOS_L3VPN_100M",
        "rd": "65000:110", "rt_import": "65000:110", "rt_export": "65000:110",
        "ce_asn": 65110, "access_node_id": "S3-9306-TEST",
        "access_interface": "Gi1/0/1", "pe_node_id": "PE2-TEST",
    }


def _parse(raw: dict[str, object]) -> L3VpnIntent:
    return parse_l3vpn_intent(raw, topology=load_default_topology())


def test_parser_resolves_mixed_route_asn_and_symmetric_targets_without_mutation() -> None:
    """Deriva identidad, interfaces y ASN y conserva el payload original."""
    raw = _raw()
    original = raw.copy()
    intent = _parse(raw)
    assert raw == original
    assert intent.pe_asn == 65000
    assert intent.ce_asn == 65110
    assert intent.lan_network is None
    assert tuple(hop.node_id for hop in intent.hops) == ("S3-9306-TEST", "S1-9306-TEST", "PE2-TEST")
    assert tuple(hop.vendor for hop in intent.hops) == ("cisco", "huawei", "huawei")
    assert intent.access.customer_port == "GigabitEthernet1/0/1"
    assert intent.provider_edge.parent_interface == "GigabitEthernet0/0/0"
    symmetric = {key: value for key, value in raw.items() if key not in ("rt_import", "rt_export")}
    assert _parse(symmetric | {"route_target": "65000:110"}) == intent
    assert _parse(raw | {"rt_export": "65000:210"}).rt_export == "65000:210"


@pytest.mark.parametrize(("canonical", "alias"), (
    ("wan_subnet", "wan_network"), ("qos_policy_name", "qos_policy"),
    ("access_interface", "client_interface"), ("lan_subnet", "lan_network"),
))
def test_aliases_are_equivalent_and_duplicates_are_rejected(canonical: str, alias: str) -> None:
    """Acepta exactamente un alias y diagnostica duplicados con el nombre canonico."""
    raw = _raw() | {"lan_network": "10.10.0.0/24"}
    value = raw.pop(canonical if canonical in raw else alias)
    assert _parse(raw | {canonical: value}) == _parse(raw | {alias: value})
    with pytest.raises(IntentParseError, match=f"^{canonical}: alias duplicado {alias}$"):
        _parse(raw | {canonical: value, alias: value})


@pytest.mark.parametrize("field", tuple(_raw()))
def test_parser_rejects_each_missing_required_input(field: str) -> None:
    """Informa el campo requerido ausente sin permitir una intencion parcial."""
    raw = _raw()
    del raw[field]
    canonical = {"wan_network": "wan_subnet", "qos_policy": "qos_policy_name"}.get(field, field)
    with pytest.raises(IntentParseError, match=f"^{canonical}: campo faltante$"):
        _parse(raw)


@pytest.mark.parametrize(("field", "value"), (
    ("service_type", None), ("service_type", "DIA"),
    ("description", " "), ("vrf_name", 1), ("qos_policy", ""),
    ("vlan_id", True), ("vlan_id", 0), ("vlan_id", 4095),
    ("bandwidth_mbps", 1.5), ("bandwidth_mbps", 0), ("bandwidth_mbps", 100001),
    ("wan_network", "172.16.10.1/30"), ("wan_network", "172.16.10.0/29"),
    ("wan_network", "2001:db8::/30"), ("wan_network", 1),
    ("lan_network", "10.0.0.0/7"), ("lan_network", "10.0.0.0/31"),
    ("lan_network", "10.0.0.1/24"), ("lan_network", "172.16.10.0/24"),
    ("rd", "01:110"), ("rd", None), ("rt_import", "65000:01"),
    ("rt_export", "192.0.2.1:65536"),
    ("ce_asn", True), ("ce_asn", 0), ("ce_asn", 4294967295), ("ce_asn", 65000),
    ("pe_asn", True), ("pe_asn", "65000"), ("pe_asn", 0), ("pe_asn", 65001),
))
def test_parser_reports_exact_input_field_for_invalid_values(field: str, value: object) -> None:
    """Rechaza tipos y valores invalidos identificando el campo de entrada."""
    with pytest.raises(IntentParseError, match=f"^{field}:"):
        _parse(_raw() | {field: value})


@pytest.mark.parametrize("field", ("rt_import", "rt_export"))
def test_route_target_modes_cannot_be_mixed(field: str) -> None:
    """Rechaza la combinacion del RT abreviado con cualquiera de los explicitos."""
    raw = {key: value for key, value in _raw().items() if key not in ("rt_import", "rt_export")}
    with pytest.raises(IntentParseError, match="^route_target: no combine"):
        _parse(raw | {"route_target": "65000:110", field: "65000:110"})
    with pytest.raises(IntentParseError, match="^route_target:"):
        _parse(raw | {"route_target": "bad"})


def test_parser_requires_mapping_topology_and_known_fields() -> None:
    """Rechaza payloads no estructurados, campos desconocidos e inventario ausente."""
    with pytest.raises(IntentParseError, match=r"^\$: se requiere un objeto"):
        parse_l3vpn_intent([])
    with pytest.raises(IntentParseError, match="^topology: inyecte un TopologyCatalog"):
        parse_l3vpn_intent(_raw())
    with pytest.raises(IntentParseError, match="^aaa: campo desconocido$"):
        _parse(_raw() | {"zzz": 1, "aaa": 2})
    with pytest.raises(IntentParseError, match="^hops: campo desconocido$"):
        _parse(_raw() | {"hops": []})


@pytest.mark.parametrize(("field", "value"), (
    ("access_node_id", "missing"), ("pe_node_id", "missing"),
    ("access_interface", "Gi1/0/99"), ("access_interface", "Gi1/0/10"),
))
def test_topology_failures_keep_input_field_and_original_cause(field: str, value: str) -> None:
    """Traduce errores de resolucion preservando el campo y la causa topologica."""
    with pytest.raises(IntentParseError, match=f"^{field}:") as error:
        _parse(_raw() | {field: value})
    assert error.value.__cause__ is not None


def test_inventory_asn_must_be_usable_and_explicit_asn_must_match() -> None:
    """Exige ASN inventariado valido y coincidencia exacta si se declara en la intencion."""
    raw = _raw()
    assert _parse(raw | {"pe_asn": None}) == _parse(raw | {"pe_asn": 65000}) == _parse(raw)
    with pytest.raises(IntentParseError, match=r"^pe_asn: ASN 65001 no coincide con el inventario de PE2-TEST \(65000\)$"):
        _parse(raw | {"pe_asn": 65001})
    topology = load_default_topology()
    reserved_asn = replace(topology, nodes=tuple(
        replace(node, asn=4294967295) if node.node_id == "PE2-TEST" else node for node in topology.nodes
    ))
    for overrides in ({}, {"pe_asn": 65000}):
        with pytest.raises(IntentParseError, match="^pe_asn:"):
            parse_l3vpn_intent(raw | overrides, topology=reserved_asn)


@pytest.mark.parametrize("service_type", ("L3VPN", "l3vpn", " L3Vpn "))
def test_registered_parser_dispatches_case_insensitively_without_mutation(service_type: str) -> None:
    """Despacha variantes del servicio registrado sin modificar el payload."""
    raw = _raw() | {"service_type": service_type}
    original = raw.copy()
    registry = IntentParserRegistry()
    registry.register(create_l3vpn_intent_parser(load_default_topology()))
    assert registry.parse(raw) == _parse(raw)
    assert raw == original


def test_parser_adapter_rejects_unregistered_vendors() -> None:
    """Impide aceptar saltos de un fabricante ajeno al catalogo inyectado."""
    parser = L3VpnIntentParser(frozenset({"cisco"}), topology=load_default_topology())
    with pytest.raises(IntentParseError, match=r"^hops\[1\].vendor: vendor no registrado 'huawei'; registrados: cisco$"):
        parser.parse(_raw())


def test_context_preserves_all_hop_fields_and_optional_lan_without_vendor_qos() -> None:
    """Expone variables canonicas y deja la composicion QoS al catalogo de plugins."""
    intent = _parse(_raw())
    for operation in Operation:
        contexts = [build_l3vpn_hop_context(intent, index, operation) for index in range(3)]
        for hop, context in zip(intent.hops, contexts, strict=True):
            assert context.items() >= {
                "service_type": "L3VPN", "operation": operation.value,
                "node_id": hop.node_id, "vendor": hop.vendor, "role": hop.role.value,
                "management_ip": str(hop.management_ip), "description": intent.description,
                "vlan_id": 110,
            }.items()
        assert contexts[0]["client_interface"] == intent.access.customer_port
        assert contexts[0]["uplink_interface"] == intent.access.uplink_interface
        assert contexts[1]["ingress_interface"] == contexts[1]["downstream_interface"] == intent.transits[0].downstream_interface
        assert contexts[1]["egress_interface"] == contexts[1]["upstream_interface"] == intent.transits[0].upstream_interface
        assert contexts[2].items() >= {
            "pe_interface": "GigabitEthernet0/0/0", "parent_interface": "GigabitEthernet0/0/0",
            "pe_subinterface": "GigabitEthernet0/0/0.110", "vrf_name": "VRF_CORP_A",
            "rd": "65000:110", "rt_import": "65000:110", "rt_export": "65000:110",
            "pe_asn": 65000, "ce_asn": 65110, "qos_policy": "QOS_L3VPN_100M",
            "bandwidth_mbps": 100, "wan_network": "172.16.10.0/30",
            "wan_pe_ip": "172.16.10.1", "wan_ce_ip": "172.16.10.2",
            "wan_netmask": "255.255.255.252", "wan_prefixlen": 30,
        }.items()
        assert {"lan_network", "cir_bps", "cir_kbps"}.isdisjoint(contexts[2])
        with_lan = build_l3vpn_hop_context(replace(intent, lan_network=IPv4Network("10.1.0.0/24")), 2, operation)
        assert with_lan.items() >= {
            "lan_network": "10.1.0.0/24", "lan_network_address": "10.1.0.0",
            "lan_prefixlen": 24, "lan_netmask": "255.255.255.0",
        }.items()


@pytest.mark.parametrize("index", (-1, 3, True, "0", None))
def test_context_rejects_invalid_hop_indices(index: object) -> None:
    """Rechaza indices fuera de ruta y tipos no enteros estrictos."""
    with pytest.raises(ValueError, match="^hop_index:"):
        build_l3vpn_hop_context(_parse(_raw()), index, Operation.PROVISION)


@pytest.mark.parametrize("network", (None, "10.0.0.0/8", "10.1.0.0/30"))
def test_optional_lan_accepts_none_and_prefix_boundaries(network: str | None) -> None:
    """Acepta LAN ausente o nula y ambos limites validos de prefijo."""
    parsed = _parse(_raw() | {"lan_subnet": network})
    assert parsed.lan_network == (None if network is None else IPv4Network(network))


def test_registry_preserves_unknown_service_spelling_and_diagnostic() -> None:
    """Conserva el valor original al diagnosticar un servicio no registrado."""
    registry = IntentParserRegistry()
    registry.register(create_l3vpn_intent_parser(load_default_topology()))
    with pytest.raises(IntentParseError) as error:
        registry.parse({"service_type": " unknown "})
    assert str(error.value) == "service_type: servicio desconocido ' unknown '; registrados: L3VPN"
