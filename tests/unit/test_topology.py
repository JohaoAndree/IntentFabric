"""Verifica integridad del inventario y resolucion determinista de rutas."""

from dataclasses import FrozenInstanceError, replace
from ipaddress import IPv4Address
from pathlib import Path

import pytest

from intentfabric.adapters.yaml_topology_repository import YamlTopologyRepository
from intentfabric.domain.errors import TopologyValidationError
from intentfabric.domain.intent import NodeRole
from intentfabric.domain.topology import OsFamily, TopologyCatalog, TopologyLink, TopologyNode


_ROOT = Path(__file__).resolve().parents[2]


def _catalog() -> TopologyCatalog:
    return YamlTopologyRepository(_ROOT / "inventory/topology.yaml").load_catalog()


def test_lab_catalog_preserves_all_nodes_links_and_metadata() -> None:
    """Carga los seis nodos y cinco enlaces exactos del laboratorio aprobado."""
    catalog = _catalog()
    assert tuple(node.node_id for node in catalog.nodes) == (
        "PE1-TEST", "PE2-TEST", "S1-4505-TEST", "S1-9306-TEST", "S3-4505-TEST", "S3-9306-TEST",
    )
    expected = (
        ("S3-9306-TEST", "cisco", "C9300L-24T-4G", "access", "192.168.56.101", "cisco_xe"),
        ("S1-9306-TEST", "huawei", "S5735-L24P4XE", "transit", "192.168.56.102", "huawei"),
        ("PE2-TEST", "huawei", "AR5710-S8T2XE", "pe", "192.168.56.103", "huawei_vrpv8"),
        ("S3-4505-TEST", "huawei", "S5735-L24P4XE", "access", "192.168.56.104", "huawei"),
        ("S1-4505-TEST", "cisco", "C9300L-24T-4G", "transit", "192.168.56.105", "cisco_xe"),
        ("PE1-TEST", "cisco", "C8200L-1N-4T", "pe", "192.168.56.106", "cisco_xe"),
    )
    for node_id, vendor, model, role, address, os_family in expected:
        node = catalog.get_node(node_id)
        assert (node.hostname, node.vendor, node.model, node.role.value, str(node.management_ip), node.os_family.value) == (
            node_id, vendor, model, role, address, os_family,
        )
    assert catalog.get_node("PE1-TEST").loopback0_ip == IPv4Address("10.255.0.1")
    assert catalog.get_node("PE2-TEST").loopback0_ip == IPv4Address("10.255.0.2")
    assert catalog.get_node("PE1-TEST").asn == catalog.get_node("PE2-TEST").asn == 65000
    assert len(catalog.links) == 5
    assert catalog == _catalog()


def test_queries_normalize_interfaces_and_ignore_link_direction() -> None:
    """Consulta puertos y vecinos canonicos sin depender del orden o sentido YAML."""
    catalog = _catalog()
    node = replace(catalog.get_node("S3-9306-TEST"), interfaces=("Gi1/0/1", "GE1/0/10"))
    assert node.interfaces == ("GigabitEthernet1/0/1", "GigabitEthernet1/0/10")
    assert node.has_interface("GE1/0/1.10")
    assert not node.has_interface("GE1/0/2")
    assert catalog.find_link_between("S3-9306-TEST", "S1-9306-TEST") == (
        "GigabitEthernet1/0/10", "GigabitEthernet1/0/24",
    )
    assert catalog.find_link_between("S1-9306-TEST", "S3-9306-TEST") == (
        "GigabitEthernet1/0/24", "GigabitEthernet1/0/10",
    )
    assert catalog.find_link_between("S3-9306-TEST", "PE2-TEST") is None
    assert catalog.find_node("absent") is None
    with pytest.raises(KeyError, match="absent"):
        catalog.get_node("absent")
    reversed_catalog = TopologyCatalog(tuple(reversed(catalog.nodes)), tuple(
        TopologyLink(link.target_node_id, link.target_interface, link.source_node_id, link.source_interface)
        for link in reversed(catalog.links)
    ))
    for node in catalog.nodes:
        assert catalog.neighbors_of(node.node_id) == reversed_catalog.neighbors_of(node.node_id)
        assert catalog.neighbors_of(node.node_id) == tuple(sorted(catalog.neighbors_of(node.node_id)))


@pytest.mark.parametrize(("attribute", "value"), (
    ("node_id", " "), ("hostname", ""), ("model", ""), ("vendor", "unknown"),
    ("os_family", OsFamily.CISCO_XE), ("interfaces", ()),
    ("interfaces", ("GE0/0/0", "GigabitEthernet0/0/0")), ("interfaces", ("unknown1",)),
    ("interfaces", ["Gi0/0/0"]), ("role", "pe"), ("management_ip", "192.0.2.1"),
    ("loopback0_ip", None), ("loopback0_ip", "10.0.0.1"),
    ("asn", None), ("asn", True), ("asn", 0), ("asn", 4294967296),
))
def test_invalid_node_metadata_is_rejected(attribute: str, value: object) -> None:
    """Rechaza identidades vacias, familias incoherentes y metadatos PE invalidos."""
    with pytest.raises(TopologyValidationError):
        replace(_catalog().get_node("PE2-TEST"), **{attribute: value})


@pytest.mark.parametrize("asn", (1, 4294967295))
def test_asn_boundaries_and_non_pe_optional_metadata(asn: int) -> None:
    """Admite extremos ASN de 32 bits y nodos no PE sin datos de loopback."""
    assert replace(_catalog().get_node("PE2-TEST"), asn=asn).asn == asn
    assert _catalog().get_node("S3-9306-TEST").loopback0_ip is None


@pytest.mark.parametrize("attribute", ("node_id", "hostname", "management_ip"))
def test_catalog_rejects_duplicate_identities(attribute: str) -> None:
    """Impide compartir identificadores, hostnames o direcciones de gestion."""
    first, second, *others = _catalog().nodes
    with pytest.raises(TopologyValidationError, match="duplicado"):
        TopologyCatalog((first, replace(second, **{attribute: getattr(first, attribute)}), *others), ())


@pytest.mark.parametrize("kind", ("missing_node", "missing_port", "occupied_port", "duplicate_link"))
def test_catalog_rejects_inconsistent_links(kind: str) -> None:
    """Impide referencias ausentes y puertos fisicos conectados mas de una vez."""
    catalog = _catalog()
    link = catalog.links[0]
    if kind == "missing_node":
        links = (replace(link, source_node_id="absent"),)
    elif kind == "missing_port":
        links = (replace(link, source_interface="Gi1/0/99"),)
    elif kind == "occupied_port":
        links = (link, TopologyLink(link.source_node_id, link.source_interface, "PE1-TEST", "Gi0/0/0"))
    else:
        links = (link, TopologyLink(link.target_node_id, link.target_interface, link.source_node_id, link.source_interface))
    with pytest.raises(TopologyValidationError):
        TopologyCatalog(catalog.nodes, links)


def test_links_reject_self_connections_and_invalid_interfaces() -> None:
    """Rechaza auto-enlaces e interfaces que no cumplen la sintaxis declarada."""
    with pytest.raises(TopologyValidationError, match="auto-enlaces"):
        TopologyLink("same", "Gi0/1", "same", "Gi0/2")
    with pytest.raises(TopologyValidationError, match="interface"):
        TopologyLink("first", "invalid", "second", "Gi0/2")
    with pytest.raises(TopologyValidationError, match="no vacia"):
        TopologyCatalog((), ())


@pytest.mark.parametrize("part", ("node", "link", "catalog"))
def test_topology_models_are_frozen(part: str) -> None:
    """Impide mutaciones de nodos, enlaces y colecciones del catalogo."""
    catalog = _catalog()
    model = {"node": catalog.nodes[0], "link": catalog.links[0], "catalog": catalog}[part]
    attribute = {"node": "node_id", "link": "source_node_id", "catalog": "nodes"}[part]
    with pytest.raises(FrozenInstanceError):
        setattr(model, attribute, "changed")


@pytest.mark.parametrize("document", (
    "", "[", "[]", "nodes: []\nlinks: []", "nodes: {}\nlinks: []",
    "nodes: []", "nodes: []\nlinks: []\nunknown: 1",
    "nodes: [null]\nlinks: []", "nodes: [{node_id: lab}]\nlinks: []",
))
def test_yaml_repository_translates_malformed_documents(tmp_path: Path, document: str) -> None:
    """Expone errores de dominio ante documentos YAML mal formados o incompletos."""
    path = tmp_path / "invalid.yaml"
    path.write_text(document, encoding="utf-8", newline="\n")
    with pytest.raises(TopologyValidationError):
        YamlTopologyRepository(path).load_catalog()


@pytest.mark.parametrize(("original", "replacement"), (
    ("vendor: cisco", "vendor: unknown"), ("os_family: cisco_xe", "os_family: unknown"),
    ("role: access", "role: unknown"), ("management_ip: 192.168.56.101", "management_ip: true"),
    ("management_ip: 192.168.56.101", "management_ip: 2001:db8::1"),
    ("asn: 65000", "asn: true"), ("source_node_id: S3-9306-TEST", "source_node_id: false"),
))
def test_yaml_repository_rejects_wrong_scalar_types(tmp_path: Path, original: str, replacement: str) -> None:
    """Rechaza tipos incompatibles y valores de enum o IPv4 desconocidos."""
    document = (_ROOT / "inventory/topology.yaml").read_text(encoding="utf-8")
    path = tmp_path / "invalid.yaml"
    path.write_text(document.replace(original, replacement), encoding="utf-8", newline="\n")
    with pytest.raises(TopologyValidationError):
        YamlTopologyRepository(path).load_catalog()


def test_yaml_repository_translates_missing_file_and_encoding_errors(tmp_path: Path) -> None:
    """Convierte archivos ausentes y bytes no UTF-8 en errores explicitos de dominio."""
    path = tmp_path / "missing.yaml"
    with pytest.raises(TopologyValidationError, match="catalogo invalido"):
        YamlTopologyRepository(path).load_catalog()
    path.write_bytes(b"\xff")
    with pytest.raises(TopologyValidationError, match="catalogo invalido"):
        YamlTopologyRepository(path).load_catalog()
