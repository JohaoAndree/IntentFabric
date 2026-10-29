"""Derivaciones puras de direccionamiento, subinterfaz y tasas QoS."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network


_KBPS_PER_MBPS = 1_000
_BPS_PER_KBPS = 1_000


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

    @property
    def cir_bps(self) -> int:
        """Expresa la tasa comprometida en bits por segundo."""
        return self.cir_kbps * _BPS_PER_KBPS

    @property
    def pir_bps(self) -> int:
        """Expresa la tasa maxima en bits por segundo."""
        return self.pir_kbps * _BPS_PER_KBPS


BandwidthRates = QosRates


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
    """Deriva CIR y PIR iguales en base decimal para un servicio garantizado.

    Exige un ancho de banda entero positivo y rechaza booleanos.
    """
    if type(bandwidth_mbps) is not int or bandwidth_mbps <= 0:
        raise ValueError("bandwidth_mbps: se requiere un entero positivo")
    rate_kbps = bandwidth_mbps * _KBPS_PER_MBPS
    return QosRates(cir_kbps=rate_kbps, pir_kbps=rate_kbps)


derive_bandwidth_rates = derive_qos_rates
