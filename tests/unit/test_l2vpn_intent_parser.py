"""Comprueba parsing estricto, topologia y contexto del circuito L2VPN."""

from dataclasses import replace
from ipaddress import IPv4Address
import re

import pytest

from intentfabric.application.intent_parsing import IntentParserRegistry
from intentfabric.bootstrap import load_default_topology
from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import L2VpnIntent
from intentfabric.domain.template_key import Operation
from intentfabric.services.l2vpn import (
    L2VpnIntentParser, build_l2vpn_hop_context, create_l2vpn_intent_parser, parse_l2vpn_intent,
)


def _raw() -> dict[str, object]:
    return {
        "service_type": "L2VPN", "description": "L2VPN-CORP-000001", "vlan_id": 310,
        "bandwidth_mbps": 100, "qos_policy": "QOS_L2VPN_100M", "pw_id": 310,
        "access_node_id": "S3-9306-TEST", "access_interface": "Gi1/0/1",
        "pe_node_id": "PE2-TEST", "remote_pe_node_id": "PE1-TEST",
    }


def _parse(raw: dict[str, object]) -> L2VpnIntent:
    return parse_l2vpn_intent(raw, topology=load_default_topology())


def test_parser_resolves_mixed_route_remote_loopback_and_defaults_without_mutation() -> None:
    """Deriva ruta, identificadores y Loopback0 remoto conservando el payload."""
    raw = _raw()
    original = raw.copy()
    intent = _parse(raw)
    assert raw == original
    assert tuple(hop.node_id for hop in intent.hops) == ("S3-9306-TEST", "S1-9306-TEST", "PE2-TEST")
    assert tuple(hop.vendor for hop in intent.hops) == ("cisco", "huawei", "huawei")
    assert intent.access.customer_port == "GigabitEthernet1/0/1"
    assert intent.provider_edge.parent_interface == "GigabitEthernet0/0/0"
    assert intent.remote_pe_ip == IPv4Address("10.255.0.1")
    assert intent.evi_id == intent.local_ac_id == intent.remote_ac_id == intent.pw_id == 310
    assert intent.rd == intent.rt_import == intent.rt_export == "65000:310"
    assert intent.instance_name == "VPWS_310"
    optional = dict.fromkeys(("evi_id", "local_ac_id", "remote_ac_id", "rd", "remote_pe_ip"))
    assert _parse(raw | optional) == intent


def test_parser_preserves_explicit_identifiers_and_route_target_modes() -> None:
    """Respeta parametros explicitos y RT simetricos o asimetricos."""
    raw = _raw() | {
        "evi_id": 410, "local_ac_id": 3101, "remote_ac_id": 3102,
        "rd": "65000:410", "remote_pe_ip": "10.255.0.1", "route_target": "65000:510",
    }
    intent = _parse(raw)
    assert (intent.evi_id, intent.local_ac_id, intent.remote_ac_id) == (410, 3101, 3102)
    assert intent.rd == "65000:410"
    assert intent.rt_import == intent.rt_export == "65000:510"
    del raw["route_target"]
    assert _parse(raw | {"rt_import": "65000:510", "rt_export": "65000:510"}) == intent
    assert _parse(raw | {"rt_import": "65000:1", "rt_export": "65000:2"}).rt_export == "65000:2"


@pytest.mark.parametrize(("canonical", "alias"), (
    ("pw_id", "vc_id"), ("qos_policy_name", "qos_policy"), ("access_interface", "client_interface"),
))
def test_aliases_are_equivalent_and_duplicates_are_rejected(canonical: str, alias: str) -> None:
    """Acepta un alias por par y rechaza duplicados con el nombre canonico."""
    raw = _raw()
    value = raw.pop(canonical if canonical in raw else alias)
    assert _parse(raw | {canonical: value}) == _parse(raw | {alias: value})
    with pytest.raises(IntentParseError, match=f"^{canonical}: alias duplicado {alias}$"):
        _parse(raw | {canonical: value, alias: value})


@pytest.mark.parametrize("field", tuple(_raw()))
def test_parser_rejects_each_missing_required_input(field: str) -> None:
    """Informa cada campo requerido ausente sin construir intenciones parciales."""
    raw = _raw()
    del raw[field]
    canonical = {"qos_policy": "qos_policy_name"}.get(field, field)
    with pytest.raises(IntentParseError, match=f"^{canonical}: campo faltante$"):
        _parse(raw)


@pytest.mark.parametrize(("field", "value"), (
    ("service_type", None), ("service_type", "DIA"), ("description", " "),
    ("description", 1), ("qos_policy", ""), ("qos_policy", None),
    ("access_node_id", " "), ("access_node_id", 1), ("pe_node_id", ""),
    ("remote_pe_node_id", " "), ("remote_pe_node_id", None),
    ("vlan_id", True), ("vlan_id", 0), ("vlan_id", 4095),
    ("bandwidth_mbps", 1.5), ("bandwidth_mbps", 0), ("bandwidth_mbps", 100001),
    ("pw_id", True), ("pw_id", 0), ("pw_id", 4294967296), ("pw_id", "310"),
    ("evi_id", True), ("evi_id", 0), ("evi_id", 65536), ("evi_id", "310"),
    ("local_ac_id", False), ("local_ac_id", 0), ("local_ac_id", 4294967296),
    ("remote_ac_id", 1.0), ("remote_ac_id", -1), ("remote_ac_id", 4294967296),
    ("rd", "01:310"), ("rd", 1), ("rt_import", "bad"), ("rt_export", "bad"),
    ("route_target", "bad"), ("route_target", None),
    ("remote_pe_ip", "2001:db8::1"), ("remote_pe_ip", 1),
    ("remote_pe_ip", "010.255.0.1"), ("remote_pe_ip", "10.255.0.1/32"),
    ("access_interface", None), ("access_interface", "invalid"),
))
def test_parser_reports_exact_input_field_for_invalid_values(field: str, value: object) -> None:
    """Rechaza tipos y valores invalidos identificando el campo provisto."""
    raw = _raw() | {field: value}
    if field in ("rt_import", "rt_export"):
        raw["rt_export" if field == "rt_import" else "rt_import"] = "65000:310"
    with pytest.raises(IntentParseError, match=f"^{field}:"):
        _parse(raw)


def test_vc_id_errors_preserve_alias_and_large_pw_requires_explicit_evi() -> None:
    """Diagnostica vc_id y exige EVI explicito si el PW supera los 16 bits."""
    raw = _raw()
    del raw["pw_id"]
    with pytest.raises(IntentParseError, match="^vc_id:"):
        _parse(raw | {"vc_id": 0})
    for evi in ({}, {"evi_id": None}):
        with pytest.raises(IntentParseError, match="^evi_id: se requiere un entero entre 1 y 65535 cuando pw_id supera 65535$"):
            _parse(raw | {"vc_id": 65536} | evi)
    intent = _parse(raw | {"vc_id": 4294967295, "evi_id": 65535})
    assert intent.local_ac_id == intent.remote_ac_id == intent.pw_id == 4294967295
    assert intent.evi_id == 65535


@pytest.mark.parametrize("field", ("rt_import", "rt_export"))
def test_route_target_modes_cannot_be_mixed_or_incomplete(field: str) -> None:
    """Rechaza RT mezclados y exige ambos campos si se declara el par."""
    with pytest.raises(IntentParseError, match="^route_target: no combine"):
        _parse(_raw() | {"route_target": "65000:310", field: "65000:310"})
    missing = "rt_export" if field == "rt_import" else "rt_import"
    with pytest.raises(IntentParseError, match=f"^{missing}: campo faltante$"):
        _parse(_raw() | {field: "65000:310"})


def test_parser_requires_mapping_topology_and_known_fields() -> None:
    """Rechaza payload no estructurado, inventario ausente y llaves desconocidas."""
    with pytest.raises(IntentParseError, match=r"^\$: se requiere un objeto"):
        parse_l2vpn_intent([])
    with pytest.raises(IntentParseError, match="^topology: inyecte un TopologyCatalog para resolver la ruta L2VPN$"):
        parse_l2vpn_intent(_raw())
    for additions in ({"zzz": 1, "aaa": 2}, {"aaa": 2, "zzz": 1}):
        with pytest.raises(IntentParseError, match="^aaa: campo desconocido$"):
            _parse(_raw() | additions)


@pytest.mark.parametrize(("field", "value"), (
    ("access_node_id", "missing"), ("pe_node_id", "missing"),
    ("access_interface", "Gi1/0/99"), ("access_interface", "Gi1/0/10"),
    ("client_interface", "Gi1/0/10"), ("pe_node_id", "PE1-TEST"),
))
def test_topology_failures_keep_input_field_and_cause(field: str, value: str) -> None:
    """Mapea errores de ruta al campo original conservando la causa topologica."""
    raw = _raw()
    if field == "client_interface":
        del raw["access_interface"]
    with pytest.raises(IntentParseError, match=f"^{field}:") as error:
        _parse(raw | {field: value})
    assert error.value.__cause__ is not None


@pytest.mark.parametrize(("changes", "message"), (
    ({"remote_pe_node_id": "PE2-TEST"}, "remote_pe_node_id: debe ser distinto de pe_node_id"),
    ({"remote_pe_node_id": "missing"}, "remote_pe_node_id: TOPOLOGY_NODE_NOT_FOUND; nodo inexistente 'missing'"),
    ({"remote_pe_node_id": "S1-9306-TEST"}, "remote_pe_node_id: TOPOLOGY_INVALID_ENDPOINT_ROLE; 'S1-9306-TEST' no es un PE con loopback0_ip"),
    ({"remote_pe_ip": "10.255.0.2"}, "remote_pe_ip: IP 10.255.0.2 no coincide con loopback0_ip de PE1-TEST (10.255.0.1)"),
))
def test_remote_endpoint_failures_match_exact_contract(changes: dict[str, object], message: str) -> None:
    """Rechaza PE local, inexistente, de otro rol o con IP discordante."""
    with pytest.raises(IntentParseError, match="^" + re.escape(message) + "$"):
        _parse(_raw() | changes)


def test_defaults_follow_inventory_asn_and_resolved_route() -> None:
    """Deriva RD y RT desde el ASN inventariado y resuelve la ruta inversa mixta."""
    topology = load_default_topology()
    topology = replace(topology, nodes=tuple(
        replace(node, asn=65100) if node.node_id == "PE2-TEST" else node for node in topology.nodes
    ))
    intent = parse_l2vpn_intent(_raw(), topology=topology)
    assert intent.rd == intent.rt_import == intent.rt_export == "65100:310"
    reverse = _parse(_raw() | {
        "access_node_id": "S3-4505-TEST", "access_interface": "GE0/0/1",
        "pe_node_id": "PE1-TEST", "remote_pe_node_id": "PE2-TEST",
    })
    assert tuple(hop.vendor for hop in reverse.hops) == ("huawei", "cisco", "cisco")
    assert reverse.remote_pe_ip == IPv4Address("10.255.0.2")


@pytest.mark.parametrize("service_type", ("L2VPN", "l2vpn", " L2Vpn "))
def test_registry_dispatches_case_insensitively_without_mutation(service_type: str) -> None:
    """Integra el parser registrado y conserva el payload original."""
    raw = _raw() | {"service_type": service_type}
    original = raw.copy()
    registry = IntentParserRegistry()
    registry.register(create_l2vpn_intent_parser(load_default_topology()))
    assert registry.parse(raw) == _parse(raw)
    assert raw == original


def test_parser_adapter_rejects_unregistered_vendors() -> None:
    """Rechaza saltos cuyo fabricante no este registrado en el catalogo."""
    parser = L2VpnIntentParser(frozenset({"cisco"}), topology=load_default_topology())
    with pytest.raises(IntentParseError, match=r"^hops\[1\].vendor: vendor no registrado 'huawei'; registrados: cisco$"):
        parser.parse(_raw())


def test_context_preserves_exact_variables_for_every_hop_and_operation() -> None:
    """Expone todas las variables canonicas y deja QoS al plugin del fabricante."""
    intent = _parse(_raw())
    for operation in Operation:
        for index, hop in enumerate(intent.hops):
            expected = {
                "service_type": "L2VPN", "operation": operation.value, "description": intent.description,
                "vlan_id": 310, "vendor": hop.vendor, "role": hop.role.value,
                "node_id": hop.node_id, "management_ip": str(hop.management_ip),
            }
            if index == 0:
                expected.update(client_interface=hop.customer_port, uplink_interface=hop.uplink_interface)
            elif index == 1:
                expected.update(downstream_interface=hop.downstream_interface, upstream_interface=hop.upstream_interface,
                                ingress_interface=hop.downstream_interface, egress_interface=hop.upstream_interface)
            else:
                expected.update(
                    pe_interface=hop.parent_interface, parent_interface=hop.parent_interface,
                    pe_subinterface="GigabitEthernet0/0/0.310", qos_policy="QOS_L2VPN_100M",
                    bandwidth_mbps=100, pw_id=310, evi_id=310, local_ac_id=310, remote_ac_id=310,
                    instance_name="VPWS_310", rd="65000:310", rt_import="65000:310", rt_export="65000:310",
                    remote_pe_node_id="PE1-TEST", remote_pe_ip="10.255.0.1",
                )
            assert build_l2vpn_hop_context(intent, index, operation) == expected


@pytest.mark.parametrize("index", (-1, 3, True, "0", None))
def test_context_rejects_invalid_hop_indices(index: object) -> None:
    """Exige un indice entero estricto dentro de la ruta."""
    with pytest.raises(ValueError, match="^hop_index: se requiere un indice entero dentro de la ruta$"):
        build_l2vpn_hop_context(_parse(_raw()), index, Operation.PROVISION)
