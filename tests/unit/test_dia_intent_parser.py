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
             "downstream_interface": "GigabitEthernet1/0/23",
             "upstream_interface": "GigabitEthernet1/0/24"},
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
    assert intent.transits[0].downstream_interface == "GigabitEthernet1/0/23"
    assert intent.transits[0].upstream_interface == "GigabitEthernet1/0/24"
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


@pytest.mark.parametrize(
    "field", ["schema_version", "service_type", "description", "vlan_id", "vrf_name",
              "wan_network", "lan_network", "bandwidth_mbps", "qos", "path"],
)
def test_every_root_field_is_required(valid_raw: dict[str, Any], field: str) -> None:
    """Exige todos los campos raíz del esquema aprobado."""
    del valid_raw[field]
    with pytest.raises(IntentParseError) as error:
        _parser().parse(valid_raw)
    assert str(error.value) == f"{field}: campo faltante"


@pytest.mark.parametrize(
    ("index", "field"),
    [(0, "vendor"), (0, "management_ip"), (0, "customer_port"), (0, "uplink_interface"),
     (1, "role"), (1, "management_ip"), (1, "downstream_interface"),
     (1, "upstream_interface"), (2, "role"), (2, "vendor"), (2, "management_ip")],
)
def test_remaining_hop_fields_are_required(
    valid_raw: dict[str, Any], index: int, field: str,
) -> None:
    """Exige los campos de salto restantes con su indice y nombre en el error."""
    del valid_raw["path"][index][field]
    with pytest.raises(IntentParseError) as error:
        _parser().parse(valid_raw)
    assert str(error.value) == f"path[{index}].{field}: campo faltante"


@pytest.mark.parametrize(
    ("location", "value", "message"),
    [(("vlan_id",), "3001", "vlan_id: se requiere un entero"),
     (("vlan_id",), 3001.0, "vlan_id: se requiere un entero"),
     (("vrf_name",), None, "vrf_name: se requiere texto"),
     (("service_type",), None, "service_type: se requiere texto"),
     (("wan_network",), 1, "wan_network: se requiere texto"),
     (("lan_network",), [], "lan_network: se requiere texto"),
     (("lan_network",), "invalid", "lan_network: red IPv4 inválida o con bits de host activos"),
     (("lan_network",), "2001:db8::/64", "lan_network: se requiere una red IPv4"),
     (("path", 0, "uplink_interface"), None, "path[0].uplink_interface: se requiere texto"),
     (("path", 1, "downstream_interface"), 1, "path[1].downstream_interface: se requiere texto"),
     (("path", 1, "upstream_interface"), False, "path[1].upstream_interface: se requiere texto"),
     (("path", 0, "vendor"), None, "path[0].vendor: se requiere texto"),
     (("path", 0, "extra"), 1, "path[0].extra: campo desconocido"),
     (("path", 2, "extra"), 1, "path[2].extra: campo desconocido")],
)
def test_remaining_field_types_are_strict(
    valid_raw: dict[str, Any], location: tuple[str | int, ...], value: Any, message: str,
) -> None:
    """Rechaza coerciones y campos extra en los contratos restantes del esquema."""
    _replace(valid_raw, location, value)
    with pytest.raises(IntentParseError) as error:
        _parser().parse(valid_raw)
    assert str(error.value) == message


@pytest.mark.parametrize("raw", [None, [], "DIA", 1])
def test_parser_requires_root_mapping(raw: Any) -> None:
    """Rechaza entradas raíz que no son objetos con campos."""
    with pytest.raises(IntentParseError) as error:
        _parser().parse(raw)
    assert str(error.value) == "$: se requiere un objeto"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_each_hop_requires_registered_vendor(valid_raw: dict[str, Any], index: int) -> None:
    """Aplica el conjunto de vendors conocidos a todos los roles de la ruta."""
    valid_raw["path"][index]["vendor"] = "other"
    with pytest.raises(IntentParseError) as error:
        _parser().parse(valid_raw)
    assert str(error.value) == (
        f"path[{index}].vendor: vendor no registrado 'other'; registrados: cisco, huawei"
    )


def _reverse_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _reverse_keys(item) for key, item in reversed(value.items())}
    if isinstance(value, list):
        return [_reverse_keys(item) for item in value]
    return value


def test_key_order_does_not_change_intent(valid_raw: dict[str, Any]) -> None:
    """Produce la misma intención al invertir las claves de todos los objetos."""
    assert _parser().parse(valid_raw) == _parser().parse(_reverse_keys(valid_raw))


@pytest.mark.parametrize("invalid_kind", ["unknown", "missing", "qos_unknown"])
def test_key_order_does_not_change_diagnostic(
    valid_raw: dict[str, Any], invalid_kind: str,
) -> None:
    """Selecciona el mismo primer error ante claves equivalentes en distinto orden."""
    if invalid_kind == "unknown":
        valid_raw.update(z_extra=1, a_extra=1)
        expected = "a_extra: campo desconocido"
    elif invalid_kind == "missing":
        del valid_raw["vlan_id"], valid_raw["description"]
        expected = "description: campo faltante"
    else:
        valid_raw["qos"].update(pir=1, cir=1)
        expected = "qos.cir: campo desconocido"
    messages = []
    for raw in [valid_raw, _reverse_keys(valid_raw)]:
        with pytest.raises(IntentParseError) as error:
            _parser().parse(raw)
        messages.append(str(error.value))
    assert messages == [expected, expected]
