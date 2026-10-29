"""Modelos inmutables de intención de servicio y saltos de la ruta."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
import re
from typing import ClassVar

from intentfabric.domain.errors import InvalidInterfaceNameError
from intentfabric.domain.interfaces import normalize_interface_name
from intentfabric.domain.template_key import NodeRole


@dataclass(frozen=True)
class ServiceIntent:
    """Representa los datos comunes de una intención de servicio."""

    description: str
    service_type: ClassVar[str]


@dataclass(frozen=True)
class AccessHop:
    """Identifica el acceso y sus interfaces de cliente y de subida."""

    node_id: str
    vendor: str
    management_ip: IPv4Address
    customer_port: str
    uplink_interface: str

    def __post_init__(self) -> None:
        customer_port, uplink_interface = _normalize_hop_interfaces(
            self.node_id, self.vendor, (self.customer_port, self.uplink_interface),
        )
        object.__setattr__(self, "customer_port", customer_port)
        object.__setattr__(self, "uplink_interface", uplink_interface)

    @property
    def role(self) -> NodeRole:
        """Identifica el salto como acceso."""
        return NodeRole.ACCESS


@dataclass(frozen=True)
class TransitHop:
    """Identifica un transito y sus interfaces aguas abajo y aguas arriba."""

    node_id: str
    vendor: str
    management_ip: IPv4Address
    downstream_interface: str
    upstream_interface: str

    def __post_init__(self) -> None:
        downstream_interface, upstream_interface = _normalize_hop_interfaces(
            self.node_id, self.vendor, (self.downstream_interface, self.upstream_interface),
        )
        object.__setattr__(self, "downstream_interface", downstream_interface)
        object.__setattr__(self, "upstream_interface", upstream_interface)

    @property
    def role(self) -> NodeRole:
        """Identifica el salto como transito."""
        return NodeRole.TRANSIT


@dataclass(frozen=True)
class ProviderEdgeHop:
    """Identifica el PE y la interfaz padre del servicio."""

    node_id: str
    vendor: str
    management_ip: IPv4Address
    parent_interface: str

    def __post_init__(self) -> None:
        (parent_interface,) = _normalize_hop_interfaces(
            self.node_id, self.vendor, (self.parent_interface,),
        )
        object.__setattr__(self, "parent_interface", parent_interface)

    @property
    def role(self) -> NodeRole:
        """Identifica el salto como PE."""
        return NodeRole.PROVIDER_EDGE


@dataclass(frozen=True)
class DiaIntent(ServiceIntent):
    """Describe un servicio DIA neutral al vendor con una ruta lineal."""

    service_type: ClassVar[str] = "DIA"
    vlan_id: int
    vrf_name: str
    wan_network: IPv4Network
    lan_network: IPv4Network
    bandwidth_mbps: int
    qos_policy_name: str
    access: AccessHop
    transits: tuple[TransitHop, ...]
    provider_edge: ProviderEdgeHop

    @property
    def hops(self) -> tuple[AccessHop | TransitHop | ProviderEdgeHop, ...]:
        """Devuelve la ruta en orden de acceso, transitos y PE."""
        return (self.access, *self.transits, self.provider_edge)


ServiceHop = AccessHop | TransitHop | ProviderEdgeHop


@dataclass(frozen=True)
class L3VpnIntent(ServiceIntent):
    """Describe un extremo L3VPN con ruta lineal y parametros eBGP PE-CE."""

    service_type: ClassVar[str] = "L3VPN"
    vlan_id: int
    vrf_name: str
    wan_network: IPv4Network
    bandwidth_mbps: int
    qos_policy_name: str
    rd: str
    rt_import: str
    rt_export: str
    pe_asn: int
    ce_asn: int
    access: AccessHop
    transits: tuple[TransitHop, ...]
    provider_edge: ProviderEdgeHop
    lan_network: IPv4Network | None = None

    @property
    def hops(self) -> tuple[ServiceHop, ...]:
        """Devuelve acceso, transitos y PE en orden de recorrido."""
        return (self.access, *self.transits, self.provider_edge)

    @property
    def qos_policy(self) -> str:
        """Expone el nombre de la politica con el alias declarativo."""
        return self.qos_policy_name


def is_valid_asn(value: int) -> bool:
    """Acepta ASN de 32 bits distintos de cero y del valor reservado maximo."""
    return type(value) is int and 1 <= value <= 4_294_967_294


def is_valid_route_distinguisher_or_target(value: str) -> bool:
    """Valida admin:assigned sin ambiguedades para los tres formatos de RFC 4364."""
    if not isinstance(value, str) or value.count(":") != 1:
        return False
    administrator, assigned = value.split(":")
    if not _is_canonical_decimal(assigned):
        return False
    assigned_number = int(assigned)
    if _is_canonical_decimal(administrator):
        administrator_number = int(administrator)
        if 1 <= administrator_number <= 65_535:
            return assigned_number <= 4_294_967_295
        return 65_536 <= administrator_number <= 4_294_967_295 and assigned_number <= 65_535
    try:
        IPv4Address(administrator)
    except ValueError:
        return False
    return assigned_number <= 65_535


def _is_canonical_decimal(value: str) -> bool:
    return len(value) <= 10 and re.fullmatch(r"0|[1-9][0-9]*", value) is not None


def _normalize_hop_interfaces(node_id: str, vendor: str, interfaces: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("node_id: se requiere texto no vacio")
    try:
        return tuple(normalize_interface_name(interface, vendor=vendor) for interface in interfaces)
    except InvalidInterfaceNameError as error:
        raise ValueError(str(error)) from error
