"""Interpreta la estructura estricta del esquema DIA v1 sin efectos externos."""

from collections.abc import Mapping
from ipaddress import IPv4Address, IPv4Network, ip_address, ip_network
from typing import Any

from intentfabric.domain.errors import IntentParseError
from intentfabric.domain.intent import AccessHop, DiaIntent, ProviderEdgeHop, TransitHop


def _mapping(raw: Any, path: str, fields: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise IntentParseError(f"{path or '$'}: se requiere un objeto")
    unknown = sorted((key for key in raw if key not in fields), key=repr)
    if unknown:
        field_path = f"{path}.{unknown[0]}" if path else str(unknown[0])
        raise IntentParseError(f"{field_path}: campo desconocido")
    for field in fields:
        if field not in raw:
            field_path = f"{path}.{field}" if path else field
            raise IntentParseError(f"{field_path}: campo faltante")
    return raw


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise IntentParseError(f"{path}: se requiere texto")
    return value


def _integer(value: Any, path: str) -> int:
    if type(value) is not int:
        raise IntentParseError(f"{path}: se requiere un entero")
    return value


def _network(value: Any, path: str) -> IPv4Network:
    value = _string(value, path)
    try:
        network = ip_network(value, strict=True)
    except ValueError as error:
        raise IntentParseError(f"{path}: red IPv4 inválida o con bits de host activos") from error
    if not isinstance(network, IPv4Network):
        raise IntentParseError(f"{path}: se requiere una red IPv4")
    return network


def _address(value: Any, path: str) -> IPv4Address:
    value = _string(value, path)
    try:
        address = ip_address(value)
    except ValueError as error:
        raise IntentParseError(f"{path}: dirección IPv4 inválida") from error
    if not isinstance(address, IPv4Address):
        raise IntentParseError(f"{path}: se requiere una dirección IPv4")
    return address


class DiaIntentParser:
    """Convierte el esquema DIA v1 a modelos con vendors registrados explícitamente."""

    service_type: str = "DIA"

    def __init__(self, known_vendors: frozenset[str]) -> None:
        self._known_vendors = known_vendors

    def _hop(
        self, raw: Any, index: int, role: str, interfaces: tuple[str, ...]
    ) -> dict[str, Any]:
        path = f"path[{index}]"
        if not isinstance(raw, Mapping):
            raise IntentParseError(f"{path}: se requiere un objeto")
        if "role" not in raw:
            raise IntentParseError(f"{path}.role: campo faltante")
        actual_role = _string(raw["role"], f"{path}.role")
        if actual_role != role:
            raise IntentParseError(f"{path}.role: se requiere {role!r} en esta posición")
        raw = _mapping(raw, path, ("role", "vendor", "management_ip") + interfaces)
        vendor = _string(raw["vendor"], f"{path}.vendor")
        if vendor not in self._known_vendors:
            registered = ", ".join(sorted(self._known_vendors)) or "ninguno"
            raise IntentParseError(
                f"{path}.vendor: vendor no registrado {vendor!r}; registrados: {registered}"
            )
        values = {
            "vendor": vendor,
            "management_ip": _address(raw["management_ip"], f"{path}.management_ip"),
        }
        for interface in interfaces:
            values[interface] = _string(raw[interface], f"{path}.{interface}")
        return values

    def parse(self, raw: Mapping[str, Any]) -> DiaIntent:
        """Valida forma, tipos y ruta de DIA v1; señala el campo inválido en el error."""
        raw = _mapping(raw, "", (
            "schema_version", "service_type", "description", "vlan_id", "vrf_name",
            "wan_network", "lan_network", "bandwidth_mbps", "qos", "path",
        ))
        if _string(raw["schema_version"], "schema_version") != "1":
            raise IntentParseError("schema_version: se requiere '1'")
        if _string(raw["service_type"], "service_type") != self.service_type:
            raise IntentParseError("service_type: se requiere 'DIA'")
        description = _string(raw["description"], "description")
        vlan_id = _integer(raw["vlan_id"], "vlan_id")
        vrf_name = _string(raw["vrf_name"], "vrf_name")
        wan_network = _network(raw["wan_network"], "wan_network")
        lan_network = _network(raw["lan_network"], "lan_network")
        bandwidth_mbps = _integer(raw["bandwidth_mbps"], "bandwidth_mbps")
        qos = _mapping(raw["qos"], "qos", ("policy_name",))
        qos_policy_name = _string(qos["policy_name"], "qos.policy_name")
        path = raw["path"]
        if not isinstance(path, list):
            raise IntentParseError("path: se requiere una lista")
        if len(path) < 2:
            raise IntentParseError("path: se requiere un acceso primero y un PE último")
        access = AccessHop(**self._hop(
            path[0], 0, "access", ("customer_port", "uplink_interface"),
        ))
        transits = tuple(
            TransitHop(**self._hop(
                hop, index, "transit", ("access_facing_interface", "pe_facing_interface"),
            ))
            for index, hop in enumerate(path[1:-1], start=1)
        )
        provider_edge = ProviderEdgeHop(**self._hop(
            path[-1], len(path) - 1, "pe", ("parent_interface",),
        ))
        return DiaIntent(
            description=description, vlan_id=vlan_id, vrf_name=vrf_name,
            wan_network=wan_network, lan_network=lan_network,
            bandwidth_mbps=bandwidth_mbps, qos_policy_name=qos_policy_name,
            access=access, transits=transits, provider_edge=provider_edge,
        )
