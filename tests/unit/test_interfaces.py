"""Garantiza normalizacion, abreviacion y rechazo de interfaces invalidas."""

import pytest

from intentfabric.domain.errors import InvalidInterfaceNameError, TopologyPathResolutionError
from intentfabric.domain.interfaces import (
    abbreviate_interface_name, are_equivalent_interfaces, normalize_interface_name,
    split_subinterface,
)


@pytest.mark.parametrize(("name", "canonical", "cisco", "huawei"), (
    ("Gi1/0/1", "GigabitEthernet1/0/1", "Gi1/0/1", "GE1/0/1"),
    ("GE0/0/0.10", "GigabitEthernet0/0/0.10", "Gi0/0/0.10", "GE0/0/0.10"),
    ("Gi0/0/4.99", "GigabitEthernet0/0/4.99", "Gi0/0/4.99", "GE0/0/4.99"),
    ("Te1/0/1", "TenGigabitEthernet1/0/1", "Te1/0/1", "10GE1/0/1"),
    ("10GE1/0/1", "TenGigabitEthernet1/0/1", "Te1/0/1", "10GE1/0/1"),
    ("XGE0/0/1", "XGigabitEthernet0/0/1", "Te0/0/1", "XGE0/0/1"),
    ("Fa0/1", "FastEthernet0/1", "Fa0/1", "Fa0/1"),
    ("Eth0/1", "Ethernet0/1", "Eth0/1", "Eth0/1"),
    ("Lo0", "Loopback0", "Lo0", "LoopBack0"),
    ("Vl10", "Vlan10", "Vl10", "Vlanif10"),
    ("Vlanif10", "Vlanif10", "Vl10", "Vlanif10"),
))
def test_supported_interfaces_have_exact_canonical_and_native_forms(
    name: str, canonical: str, cisco: str, huawei: str,
) -> None:
    """Conserva indices y expande cada familia con su abreviatura nativa."""
    assert normalize_interface_name(name) == canonical
    assert normalize_interface_name(name.swapcase()) == canonical
    assert normalize_interface_name(canonical) == canonical
    assert normalize_interface_name(name, vendor="cisco") == (
        "Vlan10" if name == "Vlanif10" else canonical
    )
    assert normalize_interface_name(name, vendor="huawei") == (
        canonical if name in ("Fa0/1", "Eth0/1") else ("Loopback0" if name == "Lo0" else huawei)
    )
    assert abbreviate_interface_name(name, "cisco") == cisco
    assert abbreviate_interface_name(name, "huawei") == huawei


def test_huawei_yunshan_native_normalization_and_vlanif_spacing() -> None:
    """Normaliza prefijos nativos YunShan OS y espacios entre Vlanif y su indice."""
    assert normalize_interface_name("GigabitEthernet0/0/1.10", vendor="huawei") == "GE0/0/1.10"
    assert normalize_interface_name("gi1/0/24", vendor="huawei") == "GE1/0/24"
    assert normalize_interface_name("ge0/0/1", vendor="huawei") == "GE0/0/1"
    assert normalize_interface_name("TenGigabitEthernet1/0/1", vendor="huawei") == "10GE1/0/1"
    assert normalize_interface_name("10ge0/0/0", vendor="huawei") == "10GE0/0/0"
    assert normalize_interface_name("multige0/0/1", vendor=" HUAWEI ") == "MultiGE0/0/1"
    assert normalize_interface_name("Vlanif 999", vendor="huawei") == "Vlanif999"
    assert normalize_interface_name("vlanif999", vendor="huawei") == "Vlanif999"
    assert normalize_interface_name("lo0", vendor="huawei") == "Loopback0"
    assert abbreviate_interface_name("lo0", "huawei") == "LoopBack0"
    assert abbreviate_interface_name("Vlanif 999", "huawei") == "Vlanif999"
    assert normalize_interface_name("MultiGE0/0/1") == "MultiGigabitEthernet0/0/1"
    assert abbreviate_interface_name("MultiGE0/0/1", "huawei") == "MultiGE0/0/1"
    for invalid_vendor in ("cisco", None, "Cisco", " CISCO "):
        with pytest.raises(InvalidInterfaceNameError):
            normalize_interface_name("Vlanif 999", vendor=invalid_vendor)
    for cisco_variant in ("cisco", "Cisco", " CISCO "):
        for multige in ("MultiGE0/0/1", "multigigabitethernet0/0/1", "mge0/0/1"):
            with pytest.raises(InvalidInterfaceNameError):
                normalize_interface_name(multige, vendor=cisco_variant)
    with pytest.raises(InvalidInterfaceNameError):
        abbreviate_interface_name("MultiGE0/0/1", "cisco")
    assert normalize_interface_name("Vlanif10", vendor="Cisco") == "Vlanif10"
    assert normalize_interface_name("Vlanif10", vendor=" CISCO ") == "Vlanif10"
    for cisco_variant in ("Cisco", " CISCO "):
        with pytest.raises(InvalidInterfaceNameError, match="vendor"):
            abbreviate_interface_name("Gi0/1", cisco_variant)


@pytest.mark.parametrize("name", (
    "", " ", "Gi 1/0/1", " Gi1/0/1", "Gi1/0/1 ", "Gi", "Gi-1", "Gi1//1",
    "Gi1/", "Gi1.0", "Gi1.4095", "Gi1.1.2", "Lo0/1", "Lo0.1", "Vl10.1",
    "Vlanif1/2", "unknown1", "Gi1\n", "Gi١", None, 1,
))
def test_invalid_interfaces_raise_domain_error(name: object) -> None:
    """Rechaza nombres mal formados y subinterfaces fuera del rango VLAN."""
    with pytest.raises(InvalidInterfaceNameError):
        normalize_interface_name(name)


@pytest.mark.parametrize("vlan", (1, 4094))
def test_subinterface_boundaries_and_parent_extraction(vlan: int) -> None:
    """Acepta los extremos VLAN y devuelve la interfaz madre canonica."""
    assert split_subinterface(f"GE0/0/0.{vlan}") == ("GigabitEthernet0/0/0", vlan)
    assert split_subinterface("Gi1/0/1") == ("GigabitEthernet1/0/1", None)


def test_equivalence_and_vlan_vendor_mapping() -> None:
    """Compara nombres canonicos con conversion VLAN especifica del fabricante."""
    assert are_equivalent_interfaces("Gi0/0/0.10", "GE0/0/0.10")
    assert not are_equivalent_interfaces("Gi0/0/0.10", "GE0/0/0.11")
    assert not are_equivalent_interfaces("Vlan10", "Vlanif10")
    for vendor, canonical in (("cisco", "Vlan10"), ("huawei", "Vlanif10")):
        assert are_equivalent_interfaces("Vl10", "Vlanif10", vendor=vendor)
        assert normalize_interface_name("Vlanif10", vendor=vendor) == canonical
        assert normalize_interface_name("Vl10", vendor=vendor) == canonical


def test_unsupported_abbreviation_vendor_is_explicit() -> None:
    """Rechaza abreviacion sin reglas declaradas para el fabricante."""
    with pytest.raises(InvalidInterfaceNameError, match="vendor"):
        abbreviate_interface_name("Gi0/1", "unknown")


def test_resolution_error_preserves_code_and_node() -> None:
    """Conserva el codigo y nodo accionables de resolucion topologica."""
    error = TopologyPathResolutionError("nodo ausente", code="TOPOLOGY_NODE_NOT_FOUND", node_id="lab")
    assert error.code == "TOPOLOGY_NODE_NOT_FOUND"
    assert error.node_id == "lab"
    assert str(error) == "nodo ausente"
