"""Verifica integridad del inventario y resolucion determinista de rutas."""

from dataclasses import FrozenInstanceError, replace
from ipaddress import IPv4Address
from pathlib import Path

import pytest

from intentfabric.adapters.yaml_topology_repository import YamlTopologyRepository
from intentfabric.application.topology import TopologyPathResolver
from intentfabric.domain.errors import TopologyPathResolutionError, TopologyValidationError
from intentfabric.domain.intent import AccessHop, NodeRole, ProviderEdgeHop, TransitHop
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


@pytest.mark.parametrize(("access_id", "pe_id", "transit_id", "client", "uplink", "ingress", "egress", "parent"), (
    ("S3-9306-TEST", "PE2-TEST", "S1-9306-TEST", "Gi1/0/1", "Gi1/0/10", "GE1/0/24", "GE1/0/25", "GE0/0/0"),
    ("S3-4505-TEST", "PE1-TEST", "S1-4505-TEST", "GE0/0/1", "GE0/0/8", "Gi1/0/11", "Gi1/0/25", "Gi0/0/4"),
))
def test_resolver_builds_exact_hops_for_both_lab_routes(
    access_id: str, pe_id: str, transit_id: str, client: str, uplink: str,
    ingress: str, egress: str, parent: str,
) -> None:
    """Resuelve ambas ramas con puertos, identidad y gestion exactos del inventario."""
    catalog = _catalog()
    resolver = TopologyPathResolver(catalog)
    assert resolver.catalog is catalog
    access, transit, pe = (catalog.get_node(identifier) for identifier in (access_id, transit_id, pe_id))
    expected = (
        AccessHop(access_id, access.vendor, access.management_ip, client, uplink),
        TransitHop(transit_id, transit.vendor, transit.management_ip, ingress, egress),
        ProviderEdgeHop(pe_id, pe.vendor, pe.management_ip, parent),
    )
    assert resolver.resolve_access_to_pe_hops(access_node_id=access_id, access_interface=client, pe_node_id=pe_id) == expected
    assert resolver.resolve_access_to_pe_hops(access_node_id=access_id, client_interface=client, pe_node_id=pe_id) == expected


@pytest.mark.parametrize(("overrides", "code", "node_id"), (
    ({"access_node_id": "absent"}, "TOPOLOGY_NODE_NOT_FOUND", "absent"),
    ({"pe_node_id": "absent"}, "TOPOLOGY_NODE_NOT_FOUND", "absent"),
    ({"access_node_id": "S1-9306-TEST"}, "TOPOLOGY_INVALID_NODE_ROLE", "S1-9306-TEST"),
    ({"pe_node_id": "S1-9306-TEST"}, "TOPOLOGY_INVALID_NODE_ROLE", "S1-9306-TEST"),
    ({"access_interface": "Gi1/0/99"}, "TOPOLOGY_INTERFACE_NOT_FOUND", "S3-9306-TEST"),
    ({"access_interface": "Gi1/0/10"}, "TOPOLOGY_CLIENT_INTERFACE_IS_TRUNK", "S3-9306-TEST"),
    ({"access_interface": "bad"}, "TOPOLOGY_INTERFACE_NOT_FOUND", "S3-9306-TEST"),
    ({"pe_node_id": "PE1-TEST"}, "TOPOLOGY_PATH_NOT_FOUND", "PE1-TEST"),
))
def test_resolver_rejects_invalid_demarcations_with_exact_codes(
    overrides: dict[str, str], code: str, node_id: str,
) -> None:
    """Distingue nodos ausentes, roles, interfaces, troncales y rutas no validas."""
    arguments = {"access_node_id": "S3-9306-TEST", "access_interface": "Gi1/0/1", "pe_node_id": "PE2-TEST"}
    with pytest.raises(TopologyPathResolutionError) as error:
        TopologyPathResolver(_catalog()).resolve_access_to_pe_hops(**(arguments | overrides))
    assert error.value.code == code
    assert error.value.node_id == node_id


def _alternative_routes() -> TopologyCatalog:
    catalog = _catalog()
    access = replace(catalog.get_node("S3-9306-TEST"), interfaces=("Gi0/1", "Gi0/2", "Gi0/3", "Gi0/4"))
    pe = replace(catalog.get_node("PE2-TEST"), interfaces=("Gi0/1", "Gi0/2", "Gi0/4"))
    transits = tuple(replace(
        catalog.get_node("S1-9306-TEST"), node_id=f"T-{letter}", hostname=f"T-{letter}",
        management_ip=IPv4Address(f"192.0.2.{index}"), interfaces=("Gi0/1", "Gi0/2", "Gi0/3"),
    ) for index, letter in enumerate(("A", "B"), start=1))
    return TopologyCatalog((access, pe, *transits), (
        TopologyLink(access.node_id, "Gi0/3", "T-B", "Gi0/1"),
        TopologyLink("T-B", "Gi0/2", pe.node_id, "Gi0/2"),
        TopologyLink(access.node_id, "Gi0/2", "T-A", "Gi0/1"),
        TopologyLink("T-A", "Gi0/2", pe.node_id, "Gi0/1"),
        TopologyLink("T-A", "Gi0/3", "T-B", "Gi0/3"),
    ))


def test_bfs_breaks_ties_deterministically_and_terminates_with_cycles() -> None:
    """Selecciona el transito lexicograficamente menor aunque existan ciclos y otro orden."""
    catalog = _alternative_routes()
    expected = None
    for links in (catalog.links, tuple(reversed(catalog.links)), tuple(
        TopologyLink(link.target_node_id, link.target_interface, link.source_node_id, link.source_interface)
        for link in catalog.links
    )):
        hops = TopologyPathResolver(TopologyCatalog(tuple(reversed(catalog.nodes)), links)).resolve_access_to_pe_hops(
            access_node_id="S3-9306-TEST", access_interface="Gi0/1", pe_node_id="PE2-TEST",
        )
        assert tuple(hop.node_id for hop in hops) == ("S3-9306-TEST", "T-A", "PE2-TEST")
        assert expected is None or hops == expected
        expected = hops


def test_bfs_prefers_direct_link_over_a_lexicographically_earlier_transit() -> None:
    """Prioriza la ruta mas corta y admite acceso a PE sin transitos."""
    catalog = _alternative_routes()
    direct = TopologyLink("S3-9306-TEST", "Gi0/4", "PE2-TEST", "Gi0/4")
    hops = TopologyPathResolver(replace(catalog, links=(*catalog.links, direct))).resolve_access_to_pe_hops(
        access_node_id="S3-9306-TEST", access_interface="Gi0/1", pe_node_id="PE2-TEST",
    )
    assert len(hops) == 2
    assert hops[0].uplink_interface == hops[1].parent_interface == "GigabitEthernet0/4"


@pytest.mark.parametrize("intermediate_role", (NodeRole.ACCESS, NodeRole.PROVIDER_EDGE))
def test_resolver_never_crosses_another_access_or_pe(intermediate_role: NodeRole) -> None:
    """Rechaza conectividad fisica que obligue a atravesar otro acceso o PE."""
    original = _alternative_routes()
    intermediate = replace(original.get_node("T-A"), role=intermediate_role, loopback0_ip=IPv4Address("10.255.0.3"), asn=65000)
    catalog = TopologyCatalog(tuple(intermediate if node.node_id == "T-A" else node for node in original.nodes), tuple(
        link for link in original.links if "T-B" not in (link.source_node_id, link.target_node_id)
    ))
    with pytest.raises(TopologyPathResolutionError) as error:
        TopologyPathResolver(catalog).resolve_access_to_pe_hops(
            access_node_id="S3-9306-TEST", access_interface="Gi0/1", pe_node_id="PE2-TEST",
        )
    assert error.value.code == "TOPOLOGY_PATH_NOT_FOUND"


def test_resolver_populates_multiple_transits_in_path_order() -> None:
    """Conserva interfaces de ingreso y salida de cada transito en rutas de varios saltos."""
    original = _alternative_routes()
    links = tuple(link for link in original.links if not (
        (link.source_node_id, link.target_node_id) in (("S3-9306-TEST", "T-B"), ("T-A", "PE2-TEST"))
    ))
    hops = TopologyPathResolver(replace(original, links=links)).resolve_access_to_pe_hops(
        access_node_id="S3-9306-TEST", access_interface="Gi0/1", pe_node_id="PE2-TEST",
    )
    assert tuple(hop.node_id for hop in hops) == ("S3-9306-TEST", "T-A", "T-B", "PE2-TEST")
    assert (hops[1].downstream_interface, hops[1].upstream_interface) == ("GigabitEthernet0/1", "GigabitEthernet0/3")
    assert (hops[2].downstream_interface, hops[2].upstream_interface) == ("GigabitEthernet0/3", "GigabitEthernet0/2")


def test_resolver_rejects_missing_or_duplicate_interface_aliases() -> None:
    """Exige una sola demarcacion de interfaz de cliente al resolver una ruta."""
    resolver = TopologyPathResolver(_catalog())
    for arguments in ({}, {"access_interface": "Gi1/0/1", "client_interface": "Gi1/0/1"}):
        with pytest.raises(TopologyPathResolutionError) as error:
            resolver.resolve_access_to_pe_hops(access_node_id="S3-9306-TEST", pe_node_id="PE2-TEST", **arguments)
        assert error.value.code == "TOPOLOGY_INTERFACE_NOT_FOUND"
