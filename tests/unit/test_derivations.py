"""Verifica los valores y el determinismo de las derivaciones de DIA."""

from dataclasses import FrozenInstanceError
from ipaddress import IPv4Address, IPv4Network

import pytest

from intentfabric.domain.derivations import (
    BandwidthRates, QosRates, WanAddresses, derive_bandwidth_rates, derive_qos_rates, derive_subinterface_name,
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
    [(50, QosRates(50_000, 50_000)), (100, QosRates(100_000, 100_000)),
     (1, QosRates(1_000, 1_000)), (2, QosRates(2_000, 2_000)),
     (3, QosRates(3_000, 3_000)), (8, QosRates(8_000, 8_000)),
     (10, QosRates(10_000, 10_000))],
)
def test_qos_rates_use_decimal_guaranteed_bandwidth(bandwidth: int, expected: QosRates) -> None:
    """Garantiza CIR igual a PIR y conversiones exactas en base decimal."""
    assert derive_qos_rates(bandwidth) == derive_qos_rates(bandwidth) == expected
    assert expected.cir_bps == expected.pir_bps == bandwidth * 1_000_000
    assert derive_bandwidth_rates(bandwidth) == expected
    assert BandwidthRates is QosRates


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
