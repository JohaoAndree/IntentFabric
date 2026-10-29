"""Interpreta intenciones L3VPN declarativas mediante demarcaciones topologicas."""

from collections.abc import Mapping
from ipaddress import IPv4Network
from typing import Any

from intentfabric.application.intent_parsing import ServiceIntentParser
from intentfabric.application.topology import TopologyPathResolver
from intentfabric.domain.errors import IntentParseError, TopologyPathResolutionError
from intentfabric.domain.intent import (
    L3VpnIntent, is_valid_asn, is_valid_route_distinguisher_or_target,
)
from intentfabric.domain.topology import TopologyCatalog


_REQUIRED_FIELDS = (
    "service_type", "description", "vlan_id", "bandwidth_mbps", "vrf_name",
    "rd", "ce_asn", "access_node_id", "pe_node_id",
)
_FIELD_ALIASES = (
    ("wan_subnet", "wan_network"),
    ("qos_policy_name", "qos_policy"), ("access_interface", "client_interface"),
)


def _mapping(raw: object) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise IntentParseError("$: se requiere un objeto")
    allowed = _REQUIRED_FIELDS + tuple(alias for pair in _FIELD_ALIASES for alias in pair) + (
        "pe_asn", "lan_subnet", "lan_network", "route_target", "rt_import", "rt_export",
    )
    unknown = sorted((key for key in raw if key not in allowed), key=repr)
    if unknown:
        raise IntentParseError(f"{unknown[0]}: campo desconocido")
    for field in _REQUIRED_FIELDS:
        if field not in raw:
            raise IntentParseError(f"{field}: campo faltante")
    for canonical, alias in _FIELD_ALIASES:
        if canonical not in raw and alias not in raw:
            raise IntentParseError(f"{canonical}: campo faltante")
        if canonical in raw and alias in raw:
            raise IntentParseError(f"{canonical}: alias duplicado {alias}")
    if "lan_subnet" in raw and "lan_network" in raw:
        raise IntentParseError("lan_subnet: alias duplicado lan_network")
    if "route_target" in raw:
        if "rt_import" in raw or "rt_export" in raw:
            raise IntentParseError("route_target: no combine route_target con rt_import o rt_export")
    else:
        for field in ("rt_import", "rt_export"):
            if field not in raw:
                raise IntentParseError(f"{field}: campo faltante")
    return raw


def _alias(raw: Mapping[str, object], canonical: str, alias: str) -> tuple[object, str]:
    field = canonical if canonical in raw else alias
    return raw[field], field


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise IntentParseError(f"{path}: se requiere texto")
    return value


def _integer(value: object, path: str) -> int:
    if type(value) is not int:
        raise IntentParseError(f"{path}: se requiere un entero")
    return value


def _network(value: object, path: str) -> IPv4Network:
    address = _string(value, path)
    try:
        return IPv4Network(address, strict=True)
    except ValueError as error:
        raise IntentParseError(f"{path}: red IPv4 invalida o con bits de host activos") from error


def _nonempty_text(value: object, field: str) -> str:
    text = _string(value, field)
    if not text.strip():
        raise IntentParseError(f"{field}: se requiere texto no vacio")
    return text


def _bounded_integer(value: object, field: str, maximum: int) -> int:
    number = _integer(value, field)
    if not 1 <= number <= maximum:
        raise IntentParseError(f"{field}: se requiere un entero entre 1 y {maximum}")
    return number


def _asn(value: object, field: str) -> int:
    number = _integer(value, field)
    if not is_valid_asn(number):
        raise IntentParseError(f"{field}: se requiere un ASN entre 1 y 4294967294")
    return number


def _route_identifier(value: object, field: str) -> str:
    value = _string(value, field)
    if not is_valid_route_distinguisher_or_target(value):
        raise IntentParseError(f"{field}: se requiere un RD o RT valido en formato admin:assigned")
    return value


def _optional_lan(raw: Mapping[str, object], wan_network: IPv4Network) -> IPv4Network | None:
    value, field = _alias(raw, "lan_subnet", "lan_network") if (
        "lan_subnet" in raw or "lan_network" in raw
    ) else (None, "lan_subnet")
    if value is None:
        return None
    network = _network(value, field)
    if not 8 <= network.prefixlen <= 30:
        raise IntentParseError(f"{field}: se requiere un prefijo entre /8 y /30")
    if wan_network.overlaps(network):
        raise IntentParseError(f"{field}: la LAN no debe solaparse con la WAN")
    return network


def parse_l3vpn_intent(
    payload: Mapping[str, object], *, topology: TopologyCatalog | None = None,
) -> L3VpnIntent:
    """Construye un extremo L3VPN estricto con ruta y ASN PE desde inventario."""
    raw = _mapping(payload)
    if _string(raw["service_type"], "service_type").strip().upper() != "L3VPN":
        raise IntentParseError("service_type: se requiere 'L3VPN' o 'l3vpn'")
    description = _nonempty_text(raw["description"], "description")
    vlan_id = _bounded_integer(raw["vlan_id"], "vlan_id", 4094)
    bandwidth = _bounded_integer(raw["bandwidth_mbps"], "bandwidth_mbps", 100000)
    vrf_name = _nonempty_text(raw["vrf_name"], "vrf_name")
    wan_value, wan_field = _alias(raw, "wan_subnet", "wan_network")
    wan_network = _network(wan_value, wan_field)
    if wan_network.prefixlen != 30:
        raise IntentParseError(f"{wan_field}: se requiere un prefijo /30")
    lan_network = _optional_lan(raw, wan_network)
    qos_policy = _nonempty_text(*_alias(raw, "qos_policy_name", "qos_policy"))
    rd = _route_identifier(raw["rd"], "rd")
    if "route_target" in raw:
        rt_import = rt_export = _route_identifier(raw["route_target"], "route_target")
    else:
        rt_import = _route_identifier(raw["rt_import"], "rt_import")
        rt_export = _route_identifier(raw["rt_export"], "rt_export")
    ce_asn = _asn(raw["ce_asn"], "ce_asn")
    access_node_id = _string(raw["access_node_id"], "access_node_id")
    pe_node_id = _string(raw["pe_node_id"], "pe_node_id")
    interface, interface_field = _alias(raw, "access_interface", "client_interface")
    interface = _string(interface, interface_field)
    if topology is None:
        raise IntentParseError("topology: inyecte un TopologyCatalog para resolver la ruta L3VPN")
    try:
        access, *transits, provider_edge = TopologyPathResolver(topology).resolve_access_to_pe_hops(
            access_node_id=access_node_id, access_interface=interface, pe_node_id=pe_node_id,
        )
    except TopologyPathResolutionError as error:
        if error.code == "TOPOLOGY_PATH_NOT_FOUND":
            field = "pe_node_id"
        elif error.code in ("TOPOLOGY_INTERFACE_NOT_FOUND", "TOPOLOGY_CLIENT_INTERFACE_IS_TRUNK"):
            field = interface_field
        else:
            field = "access_node_id" if error.node_id == access_node_id else "pe_node_id"
        raise IntentParseError(f"{field}: {error.code}; {error}") from error
    pe_node = topology.get_node(provider_edge.node_id)
    pe_asn = _asn(pe_node.asn if raw.get("pe_asn") is None else raw["pe_asn"], "pe_asn")
    if raw.get("pe_asn") is not None and pe_asn != pe_node.asn:
        raise IntentParseError(
            f"pe_asn: ASN {pe_asn} no coincide con el inventario de {provider_edge.node_id} ({pe_node.asn})"
        )
    if pe_asn == ce_asn:
        raise IntentParseError("ce_asn: debe ser distinto de pe_asn para eBGP PE-CE")
    return L3VpnIntent(
        description=description, vlan_id=vlan_id, vrf_name=vrf_name,
        wan_network=wan_network, lan_network=lan_network, bandwidth_mbps=bandwidth,
        qos_policy_name=qos_policy, rd=rd, rt_import=rt_import, rt_export=rt_export,
        pe_asn=pe_asn, ce_asn=ce_asn,
        access=access, transits=tuple(transits), provider_edge=provider_edge,
    )


class L3VpnIntentParser:
    """Adapta el parser declarativo al registro extensible existente de servicios."""

    service_type: str = "L3VPN"

    def __init__(self, known_vendors: frozenset[str], *, topology: TopologyCatalog | None = None) -> None:
        self._known_vendors = known_vendors
        self._topology = topology

    def parse(self, raw: Mapping[str, Any]) -> L3VpnIntent:
        """Interpreta L3VPN y exige que cada fabricante resuelto este registrado."""
        intent = parse_l3vpn_intent(raw, topology=self._topology)
        for index, hop in enumerate(intent.hops):
            if hop.vendor not in self._known_vendors:
                registered = ", ".join(sorted(self._known_vendors)) or "ninguno"
                raise IntentParseError(
                    f"hops[{index}].vendor: vendor no registrado {hop.vendor!r}; registrados: {registered}"
                )
        return intent


def create_l3vpn_intent_parser(topology: TopologyCatalog) -> ServiceIntentParser:
    """Provee un parser L3VPN ligado al inventario sin efectuar operaciones de E/S."""
    return L3VpnIntentParser(frozenset(node.vendor for node in topology.nodes), topology=topology)
