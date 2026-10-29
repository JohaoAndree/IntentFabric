"""Interpreta intenciones L2VPN declarativas mediante demarcaciones topologicas."""

from collections.abc import Mapping
from ipaddress import IPv4Address
from typing import Any

from intentfabric.application.intent_parsing import ServiceIntentParser
from intentfabric.application.topology import TopologyPathResolver
from intentfabric.domain.errors import IntentParseError, TopologyPathResolutionError
from intentfabric.domain.intent import (
    L2VpnIntent, is_valid_evi_id, is_valid_pseudowire_id,
    is_valid_route_distinguisher_or_target,
)
from intentfabric.domain.template_key import NodeRole
from intentfabric.domain.topology import TopologyCatalog


_REQUIRED_FIELDS = (
    "service_type", "description", "vlan_id", "bandwidth_mbps",
    "access_node_id", "pe_node_id", "remote_pe_node_id",
)
_FIELD_ALIASES = (
    ("pw_id", "vc_id"), ("qos_policy_name", "qos_policy"),
    ("access_interface", "client_interface"),
)


def _mapping(raw: object) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise IntentParseError("$: se requiere un objeto")
    allowed = _REQUIRED_FIELDS + tuple(alias for pair in _FIELD_ALIASES for alias in pair) + (
        "evi_id", "local_ac_id", "remote_ac_id", "rd", "route_target",
        "rt_import", "rt_export", "remote_pe_ip",
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
    if "route_target" in raw:
        if "rt_import" in raw or "rt_export" in raw:
            raise IntentParseError("route_target: no combine route_target con rt_import o rt_export")
    elif "rt_import" in raw or "rt_export" in raw:
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


def _pseudowire_id(value: object, field: str) -> int:
    number = _integer(value, field)
    if not is_valid_pseudowire_id(number):
        raise IntentParseError(f"{field}: se requiere un entero entre 1 y 4294967295")
    return number


def _evi_id(value: object, pw_id: int) -> int:
    if value is None:
        if not is_valid_evi_id(pw_id):
            raise IntentParseError("evi_id: se requiere un entero entre 1 y 65535 cuando pw_id supera 65535")
        return pw_id
    number = _integer(value, "evi_id")
    if not is_valid_evi_id(number):
        raise IntentParseError("evi_id: se requiere un entero entre 1 y 65535")
    return number


def _route_identifier(value: object, field: str) -> str:
    value = _string(value, field)
    if not is_valid_route_distinguisher_or_target(value):
        raise IntentParseError(f"{field}: se requiere un RD o RT valido en formato admin:assigned")
    return value


def _remote_pe_address(
    raw: Mapping[str, object], topology: TopologyCatalog,
    remote_pe_node_id: str, local_pe_node_id: str,
) -> IPv4Address:
    if remote_pe_node_id == local_pe_node_id:
        raise IntentParseError("remote_pe_node_id: debe ser distinto de pe_node_id")
    remote_pe = topology.find_node(remote_pe_node_id)
    if remote_pe is None:
        raise IntentParseError(
            f"remote_pe_node_id: TOPOLOGY_NODE_NOT_FOUND; nodo inexistente {remote_pe_node_id!r}"
        )
    if remote_pe.role != NodeRole.PROVIDER_EDGE or remote_pe.loopback0_ip is None:
        raise IntentParseError(
            f"remote_pe_node_id: TOPOLOGY_INVALID_ENDPOINT_ROLE; {remote_pe_node_id!r} no es un PE con loopback0_ip"
        )
    if raw.get("remote_pe_ip") is None:
        return remote_pe.loopback0_ip
    address = _string(raw["remote_pe_ip"], "remote_pe_ip")
    try:
        remote_pe_ip = IPv4Address(address)
    except ValueError as error:
        raise IntentParseError("remote_pe_ip: direccion IPv4 invalida") from error
    if remote_pe_ip != remote_pe.loopback0_ip:
        raise IntentParseError(
            f"remote_pe_ip: IP {remote_pe_ip} no coincide con loopback0_ip de {remote_pe_node_id} ({remote_pe.loopback0_ip})"
        )
    return remote_pe_ip


def parse_l2vpn_intent(
    payload: Mapping[str, object], *, topology: TopologyCatalog | None = None,
) -> L2VpnIntent:
    """Construye un circuito L2VPN estricto con ruta y PE remoto desde inventario."""
    raw = _mapping(payload)
    if _string(raw["service_type"], "service_type").strip().upper() != "L2VPN":
        raise IntentParseError("service_type: se requiere 'L2VPN' o 'l2vpn'")
    description = _nonempty_text(raw["description"], "description")
    vlan_id = _bounded_integer(raw["vlan_id"], "vlan_id", 4094)
    bandwidth = _bounded_integer(raw["bandwidth_mbps"], "bandwidth_mbps", 100000)
    qos_policy = _nonempty_text(*_alias(raw, "qos_policy_name", "qos_policy"))
    pw_id = _pseudowire_id(*_alias(raw, "pw_id", "vc_id"))
    evi_id = _evi_id(raw.get("evi_id"), pw_id)
    local_ac_id = _pseudowire_id(pw_id if raw.get("local_ac_id") is None else raw["local_ac_id"], "local_ac_id")
    remote_ac_id = _pseudowire_id(pw_id if raw.get("remote_ac_id") is None else raw["remote_ac_id"], "remote_ac_id")
    access_node_id = _nonempty_text(raw["access_node_id"], "access_node_id")
    pe_node_id = _nonempty_text(raw["pe_node_id"], "pe_node_id")
    remote_pe_node_id = _nonempty_text(raw["remote_pe_node_id"], "remote_pe_node_id")
    interface, interface_field = _alias(raw, "access_interface", "client_interface")
    interface = _string(interface, interface_field)
    if topology is None:
        raise IntentParseError("topology: inyecte un TopologyCatalog para resolver la ruta L2VPN")
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
    remote_pe_ip = _remote_pe_address(raw, topology, remote_pe_node_id, provider_edge.node_id)
    default_identifier = f"{pe_node.asn}:{evi_id}"
    rd = _route_identifier(default_identifier if raw.get("rd") is None else raw["rd"], "rd")
    if "route_target" in raw:
        rt_import = rt_export = _route_identifier(raw["route_target"], "route_target")
    elif "rt_import" in raw or "rt_export" in raw:
        rt_import = _route_identifier(raw["rt_import"], "rt_import")
        rt_export = _route_identifier(raw["rt_export"], "rt_export")
    else:
        rt_import = rt_export = _route_identifier(default_identifier, "route_target")
    return L2VpnIntent(
        description=description, vlan_id=vlan_id, bandwidth_mbps=bandwidth,
        qos_policy_name=qos_policy, pw_id=pw_id, evi_id=evi_id,
        local_ac_id=local_ac_id, remote_ac_id=remote_ac_id,
        rd=rd, rt_import=rt_import, rt_export=rt_export,
        remote_pe_node_id=remote_pe_node_id, remote_pe_ip=remote_pe_ip,
        access=access, transits=tuple(transits), provider_edge=provider_edge,
    )


class L2VpnIntentParser:
    """Adapta el parser declarativo al registro extensible existente de servicios."""

    service_type: str = "L2VPN"

    def __init__(self, known_vendors: frozenset[str], *, topology: TopologyCatalog | None = None) -> None:
        self._known_vendors = known_vendors
        self._topology = topology

    def parse(self, raw: Mapping[str, Any]) -> L2VpnIntent:
        """Interpreta L2VPN y exige que cada fabricante resuelto este registrado."""
        intent = parse_l2vpn_intent(raw, topology=self._topology)
        for index, hop in enumerate(intent.hops):
            if hop.vendor not in self._known_vendors:
                registered = ", ".join(sorted(self._known_vendors)) or "ninguno"
                raise IntentParseError(
                    f"hops[{index}].vendor: vendor no registrado {hop.vendor!r}; registrados: {registered}"
                )
        return intent


def create_l2vpn_intent_parser(topology: TopologyCatalog) -> ServiceIntentParser:
    """Provee un parser L2VPN ligado al inventario sin efectuar operaciones de E/S."""
    return L2VpnIntentParser(frozenset(node.vendor for node in topology.nodes), topology=topology)
