"""Comprueba el parsing estricto y determinista de la intención DIA v1."""

from copy import deepcopy
from ipaddress import IPv4Address, IPv4Network
from typing import Any

import pytest

from intentfabric.domain.errors import IntentParseError
from intentfabric.services.dia.intent_parser import DiaIntentParser


@pytest.fixture
def valid_raw() -> dict[str, Any]:
    """Proporciona una intención de laboratorio conforme al esquema v1."""
    return {
        "schema_version": "1", "service_type": "DIA", "description": "LAB#INTE#0001",
        "vlan_id": 3001, "vrf_name": "LAB-INTERNET", "wan_network": "10.255.0.0/30",
        "lan_network": "203.0.113.0/29", "bandwidth_mbps": 50,
        "qos": {"policy_name": "LAB_50MB_PARENT"},
        "path": [
            {"role": "access", "vendor": "huawei", "management_ip": "192.0.2.11",
             "customer_port": "GigabitEthernet0/0/1", "uplink_interface": "GigabitEthernet0/0/24"},
            {"role": "transit", "vendor": "cisco", "management_ip": "192.0.2.12",
             "access_facing_interface": "GigabitEthernet1/0/23",
             "pe_facing_interface": "GigabitEthernet1/0/24"},
            {"role": "pe", "vendor": "huawei", "management_ip": "192.0.2.21",
             "parent_interface": "GigabitEthernet0/0/1"},
        ],
    }


def _parser() -> DiaIntentParser:
    return DiaIntentParser(frozenset({"cisco", "huawei"}))


def _replace(raw: dict[str, Any], location: tuple[str | int, ...], value: Any) -> None:
    target = raw
    for key in location[:-1]:
        target = target[key]
    target[location[-1]] = value


def test_parser_preserves_data_and_does_not_mutate_input(valid_raw: dict[str, Any]) -> None:
    """Conserva todos los datos, convierte IPv4 y produce objetos iguales sin efectos."""
    original = deepcopy(valid_raw)
    parser = _parser()
    intent = parser.parse(valid_raw)
    assert intent == parser.parse(valid_raw)
    assert valid_raw == original
    assert intent.service_type == "DIA"
    assert intent.description == "LAB#INTE#0001"
    assert intent.vlan_id == 3001
    assert intent.vrf_name == "LAB-INTERNET"
    assert intent.wan_network == IPv4Network("10.255.0.0/30")
    assert intent.lan_network == IPv4Network("203.0.113.0/29")
    assert intent.bandwidth_mbps == 50
    assert intent.qos_policy_name == "LAB_50MB_PARENT"
    assert intent.access.vendor == "huawei"
    assert intent.access.management_ip == IPv4Address("192.0.2.11")
    assert intent.access.customer_port == "GigabitEthernet0/0/1"
    assert intent.access.uplink_interface == "GigabitEthernet0/0/24"
    assert intent.transits[0].vendor == "cisco"
    assert intent.transits[0].management_ip == IPv4Address("192.0.2.12")
    assert intent.transits[0].access_facing_interface == "GigabitEthernet1/0/23"
    assert intent.transits[0].pe_facing_interface == "GigabitEthernet1/0/24"
    assert intent.provider_edge.vendor == "huawei"
    assert intent.provider_edge.management_ip == IPv4Address("192.0.2.21")
    assert intent.provider_edge.parent_interface == "GigabitEthernet0/0/1"


@pytest.mark.parametrize(
    ("location", "value", "message"),
    [(("extra",), 1, "extra: campo desconocido"),
     (("description",), 1, "description: se requiere texto"),
     (("vlan_id",), True, "vlan_id: se requiere un entero"),
     (("bandwidth_mbps",), False, "bandwidth_mbps: se requiere un entero"),
     (("bandwidth_mbps",), 1.5, "bandwidth_mbps: se requiere un entero"),
     (("schema_version",), "2", "schema_version: se requiere '1'"),
     (("schema_version",), 1, "schema_version: se requiere texto"),
     (("service_type",), "L3VPN", "service_type: se requiere 'DIA'"),
     (("qos", "cir"), 50, "qos.cir: campo desconocido"),
     (("qos", "policy_name"), None, "qos.policy_name: se requiere texto"),
     (("qos",), [], "qos: se requiere un objeto"),
     (("wan_network",), "invalid", "wan_network: red IPv4 inválida o con bits de host activos"),
     (("wan_network",), "10.255.0.1/30", "wan_network: red IPv4 inválida o con bits de host activos"),
     (("lan_network",), "203.0.113.1/29", "lan_network: red IPv4 inválida o con bits de host activos"),
     (("wan_network",), "2001:db8::/30", "wan_network: se requiere una red IPv4"),
     (("path",), {}, "path: se requiere una lista"),
     (("path", 1), None, "path[1]: se requiere un objeto"),
     (("path", 1, "role"), True, "path[1].role: se requiere texto"),
     (("path", 1, "vendor"), "other",
      "path[1].vendor: vendor no registrado 'other'; registrados: cisco, huawei"),
     (("path", 1, "management_ip"), "invalid", "path[1].management_ip: dirección IPv4 inválida"),
     (("path", 1, "management_ip"), "2001:db8::1", "path[1].management_ip: se requiere una dirección IPv4"),
     (("path", 1, "management_ip"), 1, "path[1].management_ip: se requiere texto"),
     (("path", 1, "unexpected"), 1, "path[1].unexpected: campo desconocido"),
     (("path", 0, "customer_port"), [], "path[0].customer_port: se requiere texto"),
     (("path", 2, "parent_interface"), 1, "path[2].parent_interface: se requiere texto")],
)
def test_invalid_fields_report_exact_path(
    valid_raw: dict[str, Any], location: tuple[str | int, ...], value: Any, message: str,
) -> None:
    """Rechaza campos desconocidos, tipos erróneos y valores estructurales inválidos."""
    _replace(valid_raw, location, value)
    with pytest.raises(IntentParseError) as error:
        _parser().parse(valid_raw)
    assert str(error.value) == message


@pytest.mark.parametrize(
    ("location", "message"),
    [(("vlan_id",), "vlan_id: campo faltante"),
     (("qos", "policy_name"), "qos.policy_name: campo faltante"),
     (("path", 0, "role"), "path[0].role: campo faltante"),
     (("path", 1, "vendor"), "path[1].vendor: campo faltante"),
     (("path", 2, "parent_interface"), "path[2].parent_interface: campo faltante")],
)
def test_missing_fields_report_exact_path(
    valid_raw: dict[str, Any], location: tuple[str | int, ...], message: str,
) -> None:
    """Rechaza claves obligatorias ausentes en cada nivel del esquema."""
    target = valid_raw
    for key in location[:-1]:
        target = target[key]
    del target[location[-1]]
    with pytest.raises(IntentParseError) as error:
        _parser().parse(valid_raw)
    assert str(error.value) == message


@pytest.mark.parametrize(
    ("indices", "message"),
    [([], "path: se requiere un acceso primero y un PE último"),
     ([0], "path: se requiere un acceso primero y un PE último"),
     ([0, 1], "path[1].role: se requiere 'pe' en esta posición"),
     ([1, 2], "path[0].role: se requiere 'access' en esta posición"),
     ([1, 0, 2], "path[0].role: se requiere 'access' en esta posición"),
     ([0, 2, 2], "path[1].role: se requiere 'transit' en esta posición"),
     ([0, 0, 2], "path[1].role: se requiere 'transit' en esta posición")],
)
def test_path_requires_ordered_access_transits_and_single_pe(
    valid_raw: dict[str, Any], indices: list[int], message: str,
) -> None:
    """Exige acceso primero, tránsitos intermedios y un único PE último."""
    valid_raw["path"] = [valid_raw["path"][index] for index in indices]
    with pytest.raises(IntentParseError) as error:
        _parser().parse(valid_raw)
    assert str(error.value) == message


def test_path_allows_zero_or_multiple_transits(valid_raw: dict[str, Any]) -> None:
    """Admite rutas sin tránsito y conserva el orden de varios tránsitos."""
    access, transit, pe = valid_raw["path"]
    valid_raw["path"] = [access, pe]
    assert _parser().parse(valid_raw).transits == ()
    second = dict(transit, management_ip="192.0.2.13")
    valid_raw["path"] = [access, second, transit, pe]
    assert tuple(hop.management_ip for hop in _parser().parse(valid_raw).transits) == (
        IPv4Address("192.0.2.13"), IPv4Address("192.0.2.12"),
    )


def test_parser_leaves_semantic_rules_to_adr_005(valid_raw: dict[str, Any]) -> None:
    """Acepta tipos estructurales sin imponer rangos, descripción ni prefijos semánticos."""
    valid_raw.update(vlan_id=-1, bandwidth_mbps=0, description="", wan_network="192.0.2.0/24")
    intent = _parser().parse(valid_raw)
    assert intent.vlan_id == -1
    assert intent.bandwidth_mbps == 0
    assert intent.description == ""
    assert intent.wan_network.prefixlen == 24
