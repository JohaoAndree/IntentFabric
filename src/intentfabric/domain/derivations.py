"""Derivaciones puras de direccionamiento, subinterfaz y tasas QoS."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network


@dataclass(frozen=True)
class WanAddresses:
    """Agrupa el direccionamiento de los extremos de una WAN /30."""

    network_address: IPv4Address
    pe_address: IPv4Address
    ce_address: IPv4Address
    prefix_length: int
    netmask: str


@dataclass(frozen=True)
class QosRates:
    """Agrupa las tasas cir y pir derivadas del ancho de banda."""

    cir_kbps: int
    pir_kbps: int


def derive_wan_addresses(wan_network: IPv4Network) -> WanAddresses:
    """Asigna al PE y al CE las direcciones +1 y +2; exige una red /30."""
    if wan_network.prefixlen != 30:
        raise ValueError("wan_network: se requiere un prefijo /30")
    return WanAddresses(
        network_address=wan_network.network_address,
        pe_address=wan_network.network_address + 1,
        ce_address=wan_network.network_address + 2,
        prefix_length=wan_network.prefixlen,
        netmask=str(wan_network.netmask),
    )


def derive_subinterface_name(parent_interface: str, vlan_id: int) -> str:
    """Une la interfaz padre y la VLAN con un punto."""
    return f"{parent_interface}.{vlan_id}"


def derive_qos_rates(bandwidth_mbps: int) -> QosRates:
    """Calcula tasas enteras con redondeo hacia arriba en mitades (ADR-003 §8.2).

    Exige un ancho de banda entero positivo y rechaza booleanos.
    """
    if type(bandwidth_mbps) is not int or bandwidth_mbps <= 0:
        raise ValueError("bandwidth_mbps: se requiere un entero positivo")
    pir_kbps = ((bandwidth_mbps * 1024 * 105) + 50) // 100
    return QosRates(cir_kbps=(pir_kbps + 5) // 10, pir_kbps=pir_kbps)
