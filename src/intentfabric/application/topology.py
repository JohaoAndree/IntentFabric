"""Resuelve rutas L2 hacia PE a partir de un catalogo topologico inmutable."""

from collections import deque
from typing import Protocol

from intentfabric.domain.errors import InvalidInterfaceNameError, TopologyPathResolutionError
from intentfabric.domain.interfaces import normalize_interface_name
from intentfabric.domain.intent import AccessHop, NodeRole, ProviderEdgeHop, TransitHop
from intentfabric.domain.topology import TopologyCatalog, TopologyNode


class TopologyRepositoryPort(Protocol):
    """Define la carga de inventario sin imponer formato ni almacenamiento."""

    def load_catalog(self) -> TopologyCatalog:
        """Devuelve el catalogo validado o lanza TopologyValidationError."""
        ...


class TopologyPathResolver:
    """Selecciona mediante BFS la primera ruta minima en orden lexicografico."""

    def __init__(self, catalog: TopologyCatalog) -> None:
        self._catalog = catalog

    @property
    def catalog(self) -> TopologyCatalog:
        """Expone el catalogo inmutable utilizado para resolver rutas."""
        return self._catalog

    def resolve_access_to_pe_hops(
        self, *, access_node_id: str, pe_node_id: str,
        access_interface: str | None = None, client_interface: str | None = None,
    ) -> tuple[AccessHop, *tuple[TransitHop, ...], ProviderEdgeHop]:
        """Resuelve acceso, transitos y PE sin atravesar otros accesos ni PEs."""
        access = self._require_node(access_node_id, NodeRole.ACCESS)
        pe = self._require_node(pe_node_id, NodeRole.PROVIDER_EDGE)
        if access_interface is not None and client_interface is not None:
            raise TopologyPathResolutionError(
                "access_interface: indique un solo alias de interfaz de cliente",
                code="TOPOLOGY_INTERFACE_NOT_FOUND", node_id=access.node_id,
            )
        try:
            interface = normalize_interface_name(
                access_interface if access_interface is not None else client_interface, vendor=access.vendor,
            )
        except InvalidInterfaceNameError as error:
            raise TopologyPathResolutionError(
                f"access_interface: {error}", code="TOPOLOGY_INTERFACE_NOT_FOUND", node_id=access.node_id,
            ) from error
        if interface not in access.interfaces:
            raise TopologyPathResolutionError(
                f"access_interface: {interface!r} no existe en {access.node_id!r}",
                code="TOPOLOGY_INTERFACE_NOT_FOUND", node_id=access.node_id,
            )
        if any(local == interface for _, local, _ in self._catalog.neighbors_of(access.node_id)):
            raise TopologyPathResolutionError(
                f"access_interface: {interface!r} es un enlace troncal",
                code="TOPOLOGY_CLIENT_INTERFACE_IS_TRUNK", node_id=access.node_id,
            )
        path, ports = self._find_path(access.node_id, pe.node_id)
        transits = tuple(
            TransitHop(
                node_id=node.node_id, vendor=node.vendor, management_ip=node.management_ip,
                downstream_interface=ports[index - 1][1], upstream_interface=ports[index][0],
            )
            for index, node in enumerate((self._catalog.get_node(identifier) for identifier in path[1:-1]), start=1)
        )
        return (
            AccessHop(access.node_id, access.vendor, access.management_ip, interface, ports[0][0]),
            *transits,
            ProviderEdgeHop(pe.node_id, pe.vendor, pe.management_ip, ports[-1][1]),
        )

    def _require_node(self, node_id: str, role: NodeRole) -> TopologyNode:
        node = self._catalog.find_node(node_id)
        if node is None:
            raise TopologyPathResolutionError(
                f"node_id: nodo inexistente {node_id!r}", code="TOPOLOGY_NODE_NOT_FOUND", node_id=node_id,
            )
        if node.role != role:
            raise TopologyPathResolutionError(
                f"node_id: {node_id!r} requiere rol {role.value!r}",
                code="TOPOLOGY_INVALID_NODE_ROLE", node_id=node_id,
            )
        return node

    def _find_path(self, access_node_id: str, pe_node_id: str) -> tuple[tuple[str, ...], tuple[tuple[str, str], ...]]:
        pending: deque[tuple[tuple[str, ...], tuple[tuple[str, str], ...]]] = deque([((access_node_id,), ())])
        visited = {access_node_id}
        while pending:
            path, ports = pending.popleft()
            if path[-1] == pe_node_id:
                return path, ports
            for neighbor_id, local, remote in self._catalog.neighbors_of(path[-1]):
                neighbor = self._catalog.get_node(neighbor_id)
                if neighbor_id in visited or (
                    neighbor_id != pe_node_id and neighbor.role != NodeRole.TRANSIT
                ):
                    continue
                visited.add(neighbor_id)
                pending.append(((*path, neighbor_id), (*ports, (local, remote))))
        raise TopologyPathResolutionError(
            f"pe_node_id: no existe ruta L2 valida de {access_node_id!r} a {pe_node_id!r}",
            code="TOPOLOGY_PATH_NOT_FOUND", node_id=pe_node_id,
        )
