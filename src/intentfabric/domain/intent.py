"""Modelos inmutables de intención de servicio y saltos de la ruta."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from typing import ClassVar

from intentfabric.domain.template_key import NodeRole


@dataclass(frozen=True)
class ServiceIntent:
    """Representa los datos comunes de una intención de servicio."""

    description: str
    service_type: ClassVar[str]


@dataclass(frozen=True)
class AccessHop:
    """Identifica el acceso y sus interfaces de cliente y de subida."""

    vendor: str
    management_ip: IPv4Address
    customer_port: str
    uplink_interface: str

    @property
    def role(self) -> NodeRole:
        """Identifica el salto como acceso."""
        return NodeRole.ACCESS


@dataclass(frozen=True)
class TransitHop:
    """Identifica un transito y sus interfaces aguas abajo y aguas arriba."""

    vendor: str
    management_ip: IPv4Address
    downstream_interface: str
    upstream_interface: str

    @property
    def role(self) -> NodeRole:
        """Identifica el salto como transito."""
        return NodeRole.TRANSIT


@dataclass(frozen=True)
class ProviderEdgeHop:
    """Identifica el PE y la interfaz padre del servicio."""

    vendor: str
    management_ip: IPv4Address
    parent_interface: str

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
