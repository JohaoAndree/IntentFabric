"""Interpreta intenciones DIA declarativas mediante demarcaciones topologicas."""

from collections.abc import Mapping
from ipaddress import IPv4Network
from typing import Any

from intentfabric.application.intent_parsing import ServiceIntentParser
from intentfabric.application.topology import TopologyPathResolver
from intentfabric.domain.errors import IntentParseError, TopologyPathResolutionError
from intentfabric.domain.intent import DiaIntent
from intentfabric.domain.topology import TopologyCatalog


_REQUIRED_FIELDS = (
    "service_type", "description", "vlan_id", "bandwidth_mbps", "vrf_name",
    "access_node_id", "pe_node_id",
)
_FIELD_ALIASES = (
    ("wan_subnet", "wan_network"), ("lan_subnet", "lan_network"),
    ("qos_policy_name", "qos_policy"), ("access_interface", "client_interface"),
)


def _mapping(raw: object) -> Mapping[str, object]:
    if not isinstance(raw, Mapping):
        raise IntentParseError("$: se requiere un objeto")
    allowed = _REQUIRED_FIELDS + tuple(alias for pair in _FIELD_ALIASES for alias in pair)
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


def parse_dia_intent(payload: Mapping[str, object], *, topology: TopologyCatalog | None = None) -> DiaIntent:
    """Construye DIA con campos reales y ruta resuelta desde el inventario inyectado."""
    raw = _mapping(payload)
    if _string(raw["service_type"], "service_type").strip().upper() != "DIA":
        raise IntentParseError("service_type: se requiere 'DIA' o 'dia'")
    description = _string(raw["description"], "description")
    vlan_id = _integer(raw["vlan_id"], "vlan_id")
    bandwidth = _integer(raw["bandwidth_mbps"], "bandwidth_mbps")
    vrf_name = _string(raw["vrf_name"], "vrf_name")
    wan_network = _network(*_alias(raw, "wan_subnet", "wan_network"))
    lan_network = _network(*_alias(raw, "lan_subnet", "lan_network"))
    qos_policy = _string(*_alias(raw, "qos_policy_name", "qos_policy"))
    access_node_id = _string(raw["access_node_id"], "access_node_id")
    pe_node_id = _string(raw["pe_node_id"], "pe_node_id")
    interface, interface_field = _alias(raw, "access_interface", "client_interface")
    interface = _string(interface, interface_field)
    if topology is None:
        raise IntentParseError("topology: inyecte un TopologyCatalog para resolver la ruta DIA")
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
    return DiaIntent(
        description=description, vlan_id=vlan_id, vrf_name=vrf_name,
        wan_network=wan_network, lan_network=lan_network, bandwidth_mbps=bandwidth,
        qos_policy_name=qos_policy, access=access, transits=tuple(transits), provider_edge=provider_edge,
    )


class DiaIntentParser:
    """Adapta el parser declarativo al registro extensible existente de servicios."""

    service_type: str = "DIA"

    def __init__(self, known_vendors: frozenset[str], *, topology: TopologyCatalog | None = None) -> None:
        self._known_vendors = known_vendors
        self._topology = topology

    def parse(self, raw: Mapping[str, Any]) -> DiaIntent:
        """Interpreta DIA y exige que cada fabricante resuelto este registrado."""
        intent = parse_dia_intent(raw, topology=self._topology)
        for index, hop in enumerate(intent.hops):
            if hop.vendor not in self._known_vendors:
                registered = ", ".join(sorted(self._known_vendors)) or "ninguno"
                raise IntentParseError(
                    f"hops[{index}].vendor: vendor no registrado {hop.vendor!r}; registrados: {registered}"
                )
        return intent


def create_dia_intent_parser(topology: TopologyCatalog) -> ServiceIntentParser:
    """Provee un parser DIA ligado al inventario sin efectuar operaciones de E/S."""
    return DiaIntentParser(frozenset(node.vendor for node in topology.nodes), topology=topology)
