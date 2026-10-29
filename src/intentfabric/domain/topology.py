"""Modela un catalogo topologico inmutable con consultas deterministas."""

from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address

from intentfabric.domain.errors import InvalidInterfaceNameError, TopologyValidationError
from intentfabric.domain.interfaces import normalize_interface_name, split_subinterface
from intentfabric.domain.intent import NodeRole


class OsFamily(StrEnum):
    """Identifica la familia de sistema operativo declarada en inventario."""

    CISCO_XE = "cisco_xe"
    HUAWEI_VRP = "huawei"
    HUAWEI_VRPV8 = "huawei_vrpv8"


@dataclass(frozen=True, slots=True)
class TopologyNode:
    """Conserva identidad, gestion e interfaces canonicas de un nodo."""

    node_id: str
    hostname: str
    model: str
    vendor: str
    os_family: OsFamily
    role: NodeRole
    management_ip: IPv4Address
    interfaces: tuple[str, ...]
    loopback0_ip: IPv4Address | None = None
    asn: int | None = None

    def __post_init__(self) -> None:
        for attribute in ("node_id", "hostname", "model"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise TopologyValidationError(f"{attribute}: se requiere texto no vacio")
        compatible_families = (
            ("cisco", (OsFamily.CISCO_XE,)),
            ("huawei", (OsFamily.HUAWEI_VRP, OsFamily.HUAWEI_VRPV8)),
        )
        if not isinstance(self.os_family, OsFamily) or not any(
            self.vendor == vendor and self.os_family in families
            for vendor, families in compatible_families
        ):
            raise TopologyValidationError(f"{self.node_id}.os_family: incompatible con vendor")
        if not isinstance(self.role, NodeRole):
            raise TopologyValidationError(f"{self.node_id}.role: se requiere NodeRole")
        if not isinstance(self.management_ip, IPv4Address):
            raise TopologyValidationError(f"{self.node_id}.management_ip: se requiere IPv4Address")
        if self.loopback0_ip is not None and not isinstance(self.loopback0_ip, IPv4Address):
            raise TopologyValidationError(f"{self.node_id}.loopback0_ip: se requiere IPv4Address")
        if self.asn is not None and type(self.asn) is not int:
            raise TopologyValidationError(f"{self.node_id}.asn: se requiere None o un int exacto")
        if self.role == NodeRole.PROVIDER_EDGE and (
            self.loopback0_ip is None or self.asn is None or not 1 <= self.asn <= 4294967295
        ):
            raise TopologyValidationError(f"{self.node_id}: PE requiere loopback0_ip y asn en 1..4294967295")
        if not isinstance(self.interfaces, tuple) or not self.interfaces:
            raise TopologyValidationError(f"{self.node_id}.interfaces: se requiere una tupla no vacia")
        try:
            interfaces = tuple(normalize_interface_name(name, vendor=self.vendor) for name in self.interfaces)
        except InvalidInterfaceNameError as error:
            raise TopologyValidationError(f"{self.node_id}.interfaces: {error}") from error
        if len(set(interfaces)) != len(interfaces):
            raise TopologyValidationError(f"{self.node_id}.interfaces: interfaces duplicadas")
        object.__setattr__(self, "interfaces", interfaces)

    def has_interface(self, interface_name: str) -> bool:
        """Consulta la pertenencia de una interfaz madre normalizada."""
        parent, _ = split_subinterface(interface_name, vendor=self.vendor)
        return parent in self.interfaces


@dataclass(frozen=True, slots=True)
class TopologyLink:
    """Declara un enlace entre dos puertos canonicos de nodos distintos."""

    source_node_id: str
    source_interface: str
    target_node_id: str
    target_interface: str

    def __post_init__(self) -> None:
        for attribute in ("source_node_id", "target_node_id"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise TopologyValidationError(f"{attribute}: se requiere texto no vacio")
        if self.source_node_id == self.target_node_id:
            raise TopologyValidationError("links: no se permiten auto-enlaces")
        for attribute in ("source_interface", "target_interface"):
            try:
                canonical = normalize_interface_name(getattr(self, attribute))
            except InvalidInterfaceNameError as error:
                raise TopologyValidationError(f"{attribute}: {error}") from error
            object.__setattr__(self, attribute, canonical)


@dataclass(frozen=True, slots=True)
class TopologyCatalog:
    """Valida identidades y conexiones y ordena consultas sin estado mutable."""

    nodes: tuple[TopologyNode, ...]
    links: tuple[TopologyLink, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, tuple) or not self.nodes or not all(
            isinstance(node, TopologyNode) for node in self.nodes
        ):
            raise TopologyValidationError("nodes: se requiere una tupla no vacia de TopologyNode")
        if not isinstance(self.links, tuple) or not all(isinstance(link, TopologyLink) for link in self.links):
            raise TopologyValidationError("links: se requiere una tupla de TopologyLink")
        for attribute in ("node_id", "hostname", "management_ip"):
            values = tuple(getattr(node, attribute) for node in self.nodes)
            if len(set(values)) != len(values):
                raise TopologyValidationError(f"nodes: {attribute} duplicado")
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes, key=lambda node: node.node_id)))
        occupied_ports: set[tuple[str, str]] = set()
        for link in self.links:
            for node_id, interface in (
                (link.source_node_id, link.source_interface),
                (link.target_node_id, link.target_interface),
            ):
                node = self.find_node(node_id)
                if node is None:
                    raise TopologyValidationError(f"links: nodo inexistente {node_id!r}")
                if interface not in node.interfaces:
                    raise TopologyValidationError(f"links: interfaz {interface!r} inexistente en {node_id!r}")
                parent, _ = split_subinterface(interface, vendor=node.vendor)
                port = (node_id, parent)
                if port in occupied_ports:
                    raise TopologyValidationError(f"links: puerto conectado mas de una vez {port!r}")
                occupied_ports.add(port)

    def get_node(self, node_id: str) -> TopologyNode:
        """Obtiene el nodo solicitado o lanza KeyError si no existe."""
        node = self.find_node(node_id)
        if node is None:
            raise KeyError(node_id)
        return node

    def find_node(self, node_id: str) -> TopologyNode | None:
        """Busca un nodo por su identificador logico unico."""
        return next((node for node in self.nodes if node.node_id == node_id), None)

    def find_link_between(self, first_node_id: str, second_node_id: str) -> tuple[str, str] | None:
        """Devuelve puertos locales y remotos independientemente del sentido declarado."""
        return next((
            (local, remote) for neighbor, local, remote in self.neighbors_of(first_node_id)
            if neighbor == second_node_id
        ), None)

    def neighbors_of(self, node_id: str) -> tuple[tuple[str, str, str], ...]:
        """Devuelve vecinos y puertos incidentes en orden lexicografico."""
        neighbors: list[tuple[str, str, str]] = []
        for link in self.links:
            if link.source_node_id == node_id:
                neighbors.append((link.target_node_id, link.source_interface, link.target_interface))
            elif link.target_node_id == node_id:
                neighbors.append((link.source_node_id, link.target_interface, link.source_interface))
        return tuple(sorted(neighbors))
