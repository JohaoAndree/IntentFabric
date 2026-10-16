"""Verifica los valores y el determinismo de las derivaciones de DIA."""

from dataclasses import FrozenInstanceError
from ipaddress import IPv4Address, IPv4Network

import pytest

from intentfabric.domain.derivations import (
    QosRates, WanAddresses, derive_qos_rates, derive_subinterface_name,
    derive_wan_addresses,
)


def test_wan_addresses_match_reference() -> None:
    """Deriva las dos IP utilizables, el prefijo y la máscara de la WAN de laboratorio."""
    network = IPv4Network("10.255.0.0/30")
    expected = WanAddresses(
        IPv4Address("10.255.0.0"), IPv4Address("10.255.0.1"),
        IPv4Address("10.255.0.2"), 30, "255.255.255.252",
    )
    assert derive_wan_addresses(network) == derive_wan_addresses(network) == expected


@pytest.mark.parametrize("prefix", [0, 24, 29, 31, 32])
def test_wan_requires_prefix_30(prefix: int) -> None:
    """Rechaza prefijos que no tienen el contrato de direccionamiento /30."""
    with pytest.raises(ValueError, match="wan_network.* /30"):
        derive_wan_addresses(IPv4Network(f"192.0.2.0/{prefix}", strict=False))


def test_subinterface_uses_parent_and_vlan() -> None:
    """Forma el nombre de subinterfaz sin alterar la interfaz padre."""
    assert derive_subinterface_name("GigabitEthernet0/0/1", 3001) == (
        "GigabitEthernet0/0/1.3001"
    )


@pytest.mark.parametrize(
    ("bandwidth", "expected"),
    [(50, QosRates(5376, 53760)), (100, QosRates(10752, 107520)),
     (1, QosRates(108, 1075)), (2, QosRates(215, 2150)),
     (3, QosRates(323, 3226)), (8, QosRates(860, 8602))],
)
def test_qos_rates_follow_integer_rounding(bandwidth: int, expected: QosRates) -> None:
    """Redondea resultados fraccionarios y mitades de cir con la fórmula confirmada."""
    assert derive_qos_rates(bandwidth) == derive_qos_rates(bandwidth) == expected


@pytest.mark.parametrize("bandwidth", [0, -1, 1.5, 50.0, True, False, "50", None])
def test_qos_requires_positive_integer(bandwidth: object) -> None:
    """Rechaza anchos no positivos, fraccionarios y tipos ajenos al contrato entero."""
    with pytest.raises(ValueError, match="bandwidth_mbps.*entero positivo"):
        derive_qos_rates(bandwidth)


def test_derived_results_are_frozen() -> None:
    """Impide reasignar campos de los resultados de direccionamiento y QoS."""
    with pytest.raises(FrozenInstanceError):
        derive_qos_rates(50).cir_kbps = 1
    with pytest.raises(FrozenInstanceError):
        derive_wan_addresses(IPv4Network("10.255.0.0/30")).netmask = "changed"
