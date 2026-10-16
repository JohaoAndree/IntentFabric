"""Modelos inmutables de intención de servicio y saltos de la ruta."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
from typing import ClassVar


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


@dataclass(frozen=True)
class TransitHop:
    """Identifica un tránsito y sus interfaces hacia los extremos de la ruta."""

    vendor: str
    management_ip: IPv4Address
    access_facing_interface: str
    pe_facing_interface: str


@dataclass(frozen=True)
class ProviderEdgeHop:
    """Identifica el PE y la interfaz padre del servicio."""

    vendor: str
    management_ip: IPv4Address
    parent_interface: str


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
