"""Garantiza parsing declarativo DIA estricto con inventario inyectado."""

from copy import deepcopy
from ipaddress import IPv4Address, IPv4Network
from typing import Any

import pytest

from intentfabric.bootstrap import load_default_topology
from intentfabric.domain.errors import IntentParseError
from intentfabric.services.dia.intent_parser import (
    DiaIntentParser, create_dia_intent_parser, parse_dia_intent,
)


@pytest.fixture
def valid_raw() -> dict[str, Any]:
    """Proporciona demarcaciones y parametros de laboratorio sin datos de gestion."""
    return {
        "service_type": "DIA", "description": "TEST-0000000001", "vlan_id": 10,
        "vrf_name": "TEST-INTERNET", "wan_subnet": "192.168.10.0/30",
        "lan_subnet": "10.50.1.8/29", "bandwidth_mbps": 100,
        "qos_policy_name": "TEST_POLICY", "access_node_id": "S3-9306-TEST",
        "access_interface": "Gi1/0/1", "pe_node_id": "PE2-TEST",
    }


def _parser() -> DiaIntentParser:
    return DiaIntentParser(frozenset({"cisco", "huawei"}), topology=load_default_topology())


def test_parser_preserves_data_and_does_not_mutate_input(valid_raw: dict[str, Any]) -> None:
    """Resuelve saltos con identidad y gestion inventariadas sin alterar la entrada."""
    original = deepcopy(valid_raw)
    intent = _parser().parse(valid_raw)
    assert valid_raw == original
    assert intent == _parser().parse(valid_raw)
    assert intent.service_type == "DIA"
    assert intent.description == "TEST-0000000001"
    assert intent.vlan_id == 10
    assert intent.vrf_name == "TEST-INTERNET"
    assert intent.wan_network == IPv4Network("192.168.10.0/30")
    assert intent.lan_network == IPv4Network("10.50.1.8/29")
    assert intent.bandwidth_mbps == 100
    assert intent.qos_policy_name == "TEST_POLICY"
    assert tuple(hop.node_id for hop in intent.hops) == ("S3-9306-TEST", "S1-9306-TEST", "PE2-TEST")
    assert tuple(hop.vendor for hop in intent.hops) == ("cisco", "huawei", "huawei")
    assert intent.access.management_ip == IPv4Address("192.168.56.101")
    assert intent.access.customer_port == "GigabitEthernet1/0/1"
    assert intent.access.uplink_interface == "GigabitEthernet1/0/10"
    assert intent.transits[0].downstream_interface == "GigabitEthernet1/0/24"
    assert intent.transits[0].upstream_interface == "GigabitEthernet1/0/25"
    assert intent.provider_edge.parent_interface == "GigabitEthernet0/0/0"


@pytest.mark.parametrize("service_type", ("DIA", "dia", " Dia "))
def test_service_type_input_is_canonicalized(valid_raw: dict[str, Any], service_type: str) -> None:
    """Acepta DIA sin distincion de caja y conserva la constante interna en mayusculas."""
    valid_raw["service_type"] = service_type
    assert _parser().parse(valid_raw).service_type == "DIA"


@pytest.mark.parametrize(("canonical", "alias"), (
    ("wan_subnet", "wan_network"), ("lan_subnet", "lan_network"),
    ("qos_policy_name", "qos_policy"), ("access_interface", "client_interface"),
))
def test_aliases_produce_the_same_intent(valid_raw: dict[str, Any], canonical: str, alias: str) -> None:
    """Construye el mismo modelo desde cada alias autorizado y conserva errores de campo."""
    expected = _parser().parse(valid_raw)
    valid_raw[alias] = valid_raw.pop(canonical)
    assert _parser().parse(valid_raw) == expected
    valid_raw[canonical] = valid_raw[alias]
    with pytest.raises(IntentParseError, match=f"{canonical}: alias duplicado {alias}"):
        _parser().parse(valid_raw)


@pytest.mark.parametrize("field", (
    "service_type", "description", "vlan_id", "vrf_name", "wan_subnet", "lan_subnet",
    "bandwidth_mbps", "qos_policy_name", "access_node_id", "access_interface", "pe_node_id",
))
def test_all_required_fields_are_enforced(valid_raw: dict[str, Any], field: str) -> None:
    """Exige todos los parametros del servicio y sus tres demarcaciones."""
    del valid_raw[field]
    with pytest.raises(IntentParseError, match=f"^{field}: campo faltante$"):
        _parser().parse(valid_raw)


@pytest.mark.parametrize("field", ("hops", "path", "management_ip", "vendor", "extra", "schema_version", "qos"))
def test_unknown_and_legacy_fields_are_rejected(valid_raw: dict[str, Any], field: str) -> None:
    """Impide inyectar ruta fisica, gestion y llaves ajenas al esquema cerrado."""
    valid_raw[field] = []
    with pytest.raises(IntentParseError, match=f"^{field}: campo desconocido$"):
        _parser().parse(valid_raw)


@pytest.mark.parametrize(("field", "value", "message"), (
    ("service_type", "OTHER", "service_type: se requiere"),
    ("description", None, "description: se requiere texto"),
    ("vlan_id", True, "vlan_id: se requiere un entero"),
    ("bandwidth_mbps", 1.5, "bandwidth_mbps: se requiere un entero"),
    ("qos_policy_name", {}, "qos_policy_name: se requiere texto"),
    ("wan_subnet", "192.0.2.1/30", "wan_subnet: red IPv4 invalida"),
    ("lan_subnet", "2001:db8::/64", "lan_subnet: red IPv4 invalida"),
    ("wan_subnet", None, "wan_subnet: se requiere texto"),
    ("access_node_id", None, "access_node_id: se requiere texto"),
    ("pe_node_id", [], "pe_node_id: se requiere texto"),
    ("access_interface", 1, "access_interface: se requiere texto"),
))
def test_parser_requires_exact_scalar_types(
    valid_raw: dict[str, Any], field: str, value: object, message: str,
) -> None:
    """Rechaza coerciones y redes invalidas con diagnosticos de campo accionables."""
    valid_raw[field] = value
    with pytest.raises(IntentParseError, match=message):
        _parser().parse(valid_raw)


@pytest.mark.parametrize(("field", "value", "code"), (
    ("access_node_id", "absent", "TOPOLOGY_NODE_NOT_FOUND"),
    ("pe_node_id", "absent", "TOPOLOGY_NODE_NOT_FOUND"),
    ("access_node_id", "S1-9306-TEST", "TOPOLOGY_INVALID_NODE_ROLE"),
    ("pe_node_id", "S1-9306-TEST", "TOPOLOGY_INVALID_NODE_ROLE"),
    ("access_interface", "invalid", "TOPOLOGY_INTERFACE_NOT_FOUND"),
    ("access_interface", "Gi1/0/99", "TOPOLOGY_INTERFACE_NOT_FOUND"),
    ("access_interface", "Gi1/0/10", "TOPOLOGY_CLIENT_INTERFACE_IS_TRUNK"),
    ("pe_node_id", "PE1-TEST", "TOPOLOGY_PATH_NOT_FOUND"),
))
def test_resolution_errors_preserve_field_and_reason(
    valid_raw: dict[str, Any], field: str, value: str, code: str,
) -> None:
    """Traduce el error topologico al campo y codigo exactos del intent."""
    valid_raw[field] = value
    with pytest.raises(IntentParseError, match=f"^{field}: {code}") as error:
        _parser().parse(valid_raw)
    assert error.value.__cause__.code == code


def test_alias_error_uses_the_actual_input_field(valid_raw: dict[str, Any]) -> None:
    """Ubica el error en client_interface cuando el operador utiliza ese alias."""
    valid_raw.pop("access_interface")
    valid_raw["client_interface"] = "Gi1/0/10"
    with pytest.raises(IntentParseError, match="^client_interface: TOPOLOGY_CLIENT_INTERFACE_IS_TRUNK"):
        _parser().parse(valid_raw)


@pytest.mark.parametrize("raw", (None, [], "DIA", 1))
def test_parser_requires_root_mapping(raw: object) -> None:
    """Rechaza entradas raiz que no son objetos de intencion."""
    with pytest.raises(IntentParseError, match="se requiere un objeto"):
        _parser().parse(raw)


def test_topology_is_required_and_factory_binds_it(valid_raw: dict[str, Any]) -> None:
    """Exige inyeccion explicita y ofrece una factoria compatible con el registro."""
    with pytest.raises(IntentParseError, match="^topology:"):
        parse_dia_intent(valid_raw)
    assert create_dia_intent_parser(load_default_topology()).parse(valid_raw) == _parser().parse(valid_raw)


def test_resolved_vendors_must_be_registered(valid_raw: dict[str, Any]) -> None:
    """Aplica los vendors registrados a cada salto resuelto desde el inventario."""
    parser = DiaIntentParser(frozenset({"cisco"}), topology=load_default_topology())
    with pytest.raises(IntentParseError, match=r"hops\[1\].vendor: vendor no registrado 'huawei'"):
        parser.parse(valid_raw)


def test_key_order_does_not_change_intent_or_first_diagnostic(valid_raw: dict[str, Any]) -> None:
    """Produce el mismo modelo y primer error con claves en orden inverso."""
    reversed_raw = dict(reversed(valid_raw.items()))
    assert _parser().parse(valid_raw) == _parser().parse(reversed_raw)
    valid_raw.update(z_extra=1, a_extra=1)
    for raw in (valid_raw, dict(reversed(valid_raw.items()))):
        with pytest.raises(IntentParseError, match="^a_extra: campo desconocido$"):
            _parser().parse(raw)
