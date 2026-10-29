"""Modelos inmutables de intención de servicio y saltos de la ruta."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
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


def _normalize_hop_interfaces(node_id: str, vendor: str, interfaces: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("node_id: se requiere texto no vacio")
    try:
        return tuple(normalize_interface_name(interface, vendor=vendor) for interface in interfaces)
    except InvalidInterfaceNameError as error:
        raise ValueError(str(error)) from error
