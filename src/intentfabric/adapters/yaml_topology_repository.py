"""Carga y valida el inventario YAML en el borde de entrada del framework."""

from collections.abc import Mapping
from ipaddress import IPv4Address
from pathlib import Path

import yaml

from intentfabric.domain.errors import TopologyValidationError
from intentfabric.domain.intent import NodeRole
from intentfabric.domain.topology import OsFamily, TopologyCatalog, TopologyLink, TopologyNode


def _fields(value: object, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TopologyValidationError("topology: se requiere un objeto")
    unknown = sorted((key for key in value if key not in required + optional), key=repr)
    if unknown:
        raise TopologyValidationError(f"topology: campo desconocido {unknown[0]!r}")
    for key in required:
        if key not in value:
            raise TopologyValidationError(f"topology: campo faltante {key!r}")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TopologyValidationError(f"{field}: se requiere texto no vacio")
    return value


def _node(value: object) -> TopologyNode:
    attributes = _fields(value, (
        "node_id", "hostname", "model", "vendor", "os_family", "role", "management_ip", "interfaces",
    ), ("loopback0_ip", "asn"))
    interfaces = attributes["interfaces"]
    if not isinstance(interfaces, list):
        raise TopologyValidationError("interfaces: se requiere una lista")
    return TopologyNode(
        node_id=_text(attributes["node_id"], "node_id"),
        hostname=_text(attributes["hostname"], "hostname"),
        model=_text(attributes["model"], "model"),
        vendor=_text(attributes["vendor"], "vendor"),
        os_family=OsFamily(_text(attributes["os_family"], "os_family")),
        role=NodeRole(_text(attributes["role"], "role")),
        management_ip=IPv4Address(_text(attributes["management_ip"], "management_ip")),
        interfaces=tuple(_text(interface, "interfaces") for interface in interfaces),
        loopback0_ip=(IPv4Address(_text(attributes["loopback0_ip"], "loopback0_ip"))
                      if attributes.get("loopback0_ip") is not None else None),
        asn=attributes.get("asn"),
    )


def _link(value: object) -> TopologyLink:
    fields = ("source_node_id", "source_interface", "target_node_id", "target_interface")
    attributes = _fields(value, fields)
    return TopologyLink(**{field: _text(attributes[field], field) for field in fields})


class YamlTopologyRepository:
    """Materializa un catalogo inmutable desde un archivo YAML local."""

    def __init__(self, path: Path | str = Path("inventory/topology.yaml")) -> None:
        self._path = Path(path)

    def load_catalog(self) -> TopologyCatalog:
        """Carga el catalogo o traduce fallos de lectura y formato a error de dominio."""
        try:
            with self._path.open(encoding="utf-8", newline="\n") as stream:
                document = yaml.safe_load(stream)
            attributes = _fields(document, ("nodes", "links"))
            if not isinstance(attributes["nodes"], list) or not isinstance(attributes["links"], list):
                raise TopologyValidationError("nodes y links: se requieren listas")
            return TopologyCatalog(
                nodes=tuple(_node(node) for node in attributes["nodes"]),
                links=tuple(_link(link) for link in attributes["links"]),
            )
        except (OSError, UnicodeError, yaml.YAMLError, ValueError, TypeError) as error:
            raise TopologyValidationError(f"{self._path}: catalogo invalido; {error}") from error
